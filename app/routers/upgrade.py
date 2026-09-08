import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBPaymentHistory, DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    charge_authorization,
    create_subscription,
    disable_subscription,
    fetch_customer_subscriptions_by_code,
    fetch_plan,
    fetch_subscription,
    get_plan_code,
    initialize_transaction,
    verify_transaction,
    verify_webhook_signature,
)
from app.subscription_upgrade import DBSubscriptionUpgrade

router = APIRouter(prefix="/payments", tags=["Payments"])
PAID_PLANS = {"essential", "pro"}
VALID_INTERVALS = {"month", "year"}
PLAN_RANK = {"essential": 1, "pro": 2}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def get_metadata(subscription: DBSubscription) -> dict:
    if not subscription.metadata_json:
        return {}
    try:
        value = json.loads(subscription.metadata_json)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def set_metadata(subscription: DBSubscription, value: dict) -> None:
    subscription.metadata_json = json.dumps(value)


def add_billing_period(start: datetime, interval: str) -> datetime:
    start = parse_datetime(start) or now_utc()
    if interval == "year":
        try:
            return start.replace(year=start.year + 1)
        except ValueError:
            return start.replace(year=start.year + 1, day=28)
    month = start.month + 1
    year = start.year
    if month > 12:
        month = 1
        year += 1
    days = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return start.replace(year=year, month=month, day=min(start.day, days[month - 1]))


def calculate_first_debit(now: datetime, target_interval: str, unused_credit_kobo: int, target_price_kobo: int, upgrade_amount_kobo: int) -> tuple[datetime, int]:
    now = parse_datetime(now) or now_utc()
    first_period_end = add_billing_period(now, target_interval)
    period_seconds = Decimal(str((first_period_end - now).total_seconds()))
    target_price = Decimal(max(target_price_kobo, 1))
    unused = Decimal(max(unused_credit_kobo, 0))
    if upgrade_amount_kobo > 0:
        duration = int(period_seconds.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return first_period_end, duration
    covered_periods = max(Decimal("1"), unused / target_price)
    duration = int((period_seconds * covered_periods).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return now + timedelta(seconds=duration), duration


async def get_user_subscription(db: AsyncSession, user_id: int, *, lock: bool = False) -> DBSubscription | None:
    query = select(DBSubscription).where(DBSubscription.user_id == user_id)
    if lock:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_upgrade_context(db: AsyncSession, current_user: DBUser, plan: str, interval: str, *, lock: bool = False) -> dict:
    plan = plan.strip().lower()
    interval = interval.strip().lower()
    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid paid subscription plan")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid billing interval. Use month or year.")

    subscription = await get_user_subscription(db, current_user.id, lock=lock)
    if not subscription:
        raise HTTPException(status_code=400, detail="No subscription record found")

    metadata = get_metadata(subscription)
    current_plan = str(current_user.plan or subscription.plan or "").strip().lower()
    current_interval = str(metadata.get("interval") or "").strip().lower()
    recurring = bool(subscription.authorization_code and subscription.paystack_subscription_code)
    if current_plan == plan and current_interval == interval:
        raise HTTPException(status_code=400, detail="You are already on this plan and billing interval")
    if PLAN_RANK.get(plan, 0) <= PLAN_RANK.get(current_plan, 0):
        raise HTTPException(status_code=400, detail="The selected subscription is not an upgrade")

    try:
        current_plan_data = await fetch_plan(get_plan_code(current_plan, current_interval))
        target_plan_data = await fetch_plan(get_plan_code(plan, interval))
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    current_price_kobo = int((current_plan_data.get("data") or {}).get("amount") or 0)
    target_price_kobo = int((target_plan_data.get("data") or {}).get("amount") or 0)
    if current_price_kobo <= 0 or target_price_kobo <= 0:
        raise HTTPException(status_code=502, detail="Could not determine subscription prices from Paystack")

    if recurring:
        try:
            current_remote = await fetch_subscription(subscription.paystack_subscription_code)
        except PaystackError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        remote_data = current_remote.get("data") or {}
        period_start = parse_datetime(remote_data.get("start")) or subscription.updated_at
        period_end = parse_datetime(remote_data.get("next_payment_date")) or subscription.current_period_end
    else:
        period_start = subscription.current_period_start
        period_end = subscription.current_period_end
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="Could not determine the current billing period")
    period_start = period_start.astimezone(timezone.utc)
    period_end = period_end.astimezone(timezone.utc)
    now = now_utc()
    if period_end <= now:
        raise HTTPException(status_code=400, detail="The current subscription period has ended")

    total_seconds = int((period_end - period_start).total_seconds())
    remaining_seconds = max(int((period_end - now).total_seconds()), 0)
    if total_seconds <= 0:
        raise HTTPException(status_code=400, detail="Invalid current billing period")

    unused_value_kobo = int((Decimal(current_price_kobo) * Decimal(remaining_seconds) / Decimal(total_seconds)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    upgrade_amount_kobo = max(target_price_kobo - unused_value_kobo, 0)
    first_debit, credit_duration_seconds = calculate_first_debit(now, interval, unused_value_kobo, target_price_kobo, upgrade_amount_kobo)

    return {
        "subscription": subscription,
        "metadata": metadata,
        "recurring": recurring,
        "current_plan": current_plan,
        "current_interval": current_interval,
        "new_plan": plan,
        "new_interval": interval,
        "period_start": period_start,
        "period_end": period_end,
        "total_seconds": total_seconds,
        "remaining_seconds": remaining_seconds,
        "total_days": total_seconds / 86400,
        "remaining_days": remaining_seconds / 86400,
        "current_plan_price_kobo": current_price_kobo,
        "new_plan_price_kobo": target_price_kobo,
        "current_plan_price": current_price_kobo / 100,
        "new_plan_price": target_price_kobo / 100,
        "unused_value_kobo": unused_value_kobo,
        "unused_value": unused_value_kobo / 100,
        "upgrade_amount_kobo": upgrade_amount_kobo,
        "upgrade_amount": upgrade_amount_kobo / 100,
        "credit_duration_seconds": credit_duration_seconds,
        "first_debit": first_debit,
    }


async def get_pending_upgrade(db: AsyncSession, user_id: int, *, lock: bool = False) -> DBSubscriptionUpgrade | None:
    query = select(DBSubscriptionUpgrade).where(
        DBSubscriptionUpgrade.user_id == user_id,
        DBSubscriptionUpgrade.status.in_(["pending_payment", "payment_success", "creating_subscription", "subscription_created", "cleanup_pending"]),
    ).order_by(DBSubscriptionUpgrade.id.desc()).limit(1)
    if lock:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_upgrade_by_reference(db: AsyncSession, reference: str, *, lock: bool = False) -> DBSubscriptionUpgrade | None:
    query = select(DBSubscriptionUpgrade).where((DBSubscriptionUpgrade.reference == reference) | (DBSubscriptionUpgrade.payment_reference == reference))
    if lock:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def record_upgrade_payment(db: AsyncSession, upgrade: DBSubscriptionUpgrade, user: DBUser, amount_kobo: int, channel: str, paid_at: datetime) -> None:
    if amount_kobo <= 0 or not upgrade.payment_reference:
        return
    stmt = insert(DBPaymentHistory).values(
        user_id=user.id,
        subscription_id=upgrade.subscription_id,
        payment_id=f"ES-PAY-{uuid.uuid4().hex}",
        receipt_number=f"ES-RCP-{uuid.uuid4().hex}",
        provider="paystack",
        provider_reference=upgrade.payment_reference,
        billing_type="one_time",
        method=channel or None,
        reference=upgrade.payment_reference,
        plan=upgrade.new_plan,
        interval=upgrade.new_interval,
        amount=amount_kobo / 100,
        currency="NGN",
        status="success",
        event="subscription.upgrade.payment",
        paid_at=paid_at,
        created_at=now_utc(),
    ).on_conflict_do_nothing(index_elements=[DBPaymentHistory.reference])
    await db.execute(stmt)


async def disable_old_subscription(subscription_code: str, local_email_token: str | None = None) -> dict:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            remote = await fetch_subscription(subscription_code)
            data = remote.get("data") or {}
            status = str(data.get("status") or "").lower()
            if status in {"cancelled", "canceled", "completed", "non-renewing"}:
                return data
            token = data.get("email_token") or local_email_token
            if not token:
                raise PaystackError("Paystack did not return an email token for the old subscription")
            await disable_subscription(subscription_code, token)
            verify = await fetch_subscription(subscription_code)
            verify_data = verify.get("data") or {}
            verify_status = str(verify_data.get("status") or "").lower()
            if verify_status in {"cancelled", "canceled", "completed", "non-renewing"}:
                return verify_data
            raise PaystackError(f"Old subscription remains in unexpected status: {verify_status or 'unknown'}")
        except PaystackError as exc:
            last_error = exc
    raise PaystackError(f"Could not disable old Paystack subscription {subscription_code}: {last_error}")


async def create_target_subscription(*, subscription: DBSubscription, upgrade: DBSubscriptionUpgrade, authorization_code: str) -> dict:
    if not subscription.paystack_customer_code:
        raise PaystackError("Paystack customer information is missing")
    plan_code = get_plan_code(upgrade.new_plan, upgrade.new_interval)
    try:
        result = await create_subscription(
            customer=subscription.paystack_customer_code,
            plan_code=plan_code,
            authorization_code=authorization_code,
            start_date=upgrade.first_debit.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        )
    except PaystackError:
        existing = await _find_existing_target_subscription(subscription.paystack_customer_code, plan_code)
        if existing:
            return existing
        raise
    data = result.get("data") or {}
    if not data.get("subscription_code"):
        raise PaystackError("Paystack did not return the new subscription code")
    return data


async def _find_existing_target_subscription(customer_code: str, plan_code: str) -> dict | None:
    try:
        subs = (await fetch_customer_subscriptions_by_code(customer_code)).get("data") or []
    except PaystackError:
        return None
    matches = [s for s in subs if (s.get("plan") or {}).get("plan_code") == plan_code and str(s.get("status") or "").lower() in ("active", "non-renewing")]
    if not matches:
        return None
    matches.sort(key=lambda s: s.get("createdAt") or "", reverse=True)
    return matches[0]


async def complete_upgrade(db: AsyncSession, user: DBUser, subscription: DBSubscription, upgrade: DBSubscriptionUpgrade, *, authorization_code: str, payment_channel: str, paid_at: datetime | None = None, payment_amount_kobo: int = 0) -> dict:
    if upgrade.status == "completed" and upgrade.new_subscription_code:
        return {"status": "success", "plan": upgrade.new_plan, "interval": upgrade.new_interval, "subscription_code": upgrade.new_subscription_code, "reference": upgrade.payment_reference or upgrade.reference, "first_debit": upgrade.first_debit}

    if not authorization_code:
        raise HTTPException(status_code=502, detail="No reusable authorization is available for the new subscription")

    if upgrade.new_subscription_code:
        try:
            target_data = (await fetch_subscription(upgrade.new_subscription_code)).get("data") or {}
        except PaystackError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        upgrade.status = "creating_subscription"
        upgrade.updated_at = now_utc()
        await db.commit()
        try:
            target_data = await create_target_subscription(subscription=subscription, upgrade=upgrade, authorization_code=authorization_code)
        except PaystackError as exc:
            upgrade.status = "payment_success" if payment_amount_kobo > 0 else "creating_subscription"
            upgrade.last_error = str(exc)
            upgrade.updated_at = now_utc()
            await db.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        # Creating the target subscription is not itself a pending payment state.
        # A payment-backed upgrade is marked pending when its Paystack transaction
        # is initialized; once we reach this function, the upgrade can be finalized.
        upgrade.new_subscription_code = target_data["subscription_code"]
        upgrade.new_authorization_code = (target_data.get("authorization") or {}).get("authorization_code") or authorization_code
        upgrade.status = "subscription_created"
        upgrade.updated_at = now_utc()
        await db.commit()

    try:
        old_data = await disable_old_subscription(upgrade.old_subscription_code, subscription.paystack_email_token)
    except PaystackError as exc:
        upgrade.status = "cleanup_pending"
        upgrade.last_error = str(exc)
        upgrade.updated_at = now_utc()
        await db.commit()
        raise HTTPException(status_code=502, detail="Upgrade is paid and the new subscription exists, but the old subscription could not be disabled yet. Retry verification to finish cleanup.") from exc

    paid_at = paid_at or now_utc()
    target_data = target_data or {}
    period_start = parse_datetime(target_data.get("start")) or paid_at
    period_end = parse_datetime(target_data.get("next_payment_date")) or upgrade.first_debit
    if period_end <= period_start:
        period_end = upgrade.first_debit

    subscription.plan = upgrade.new_plan
    subscription.status = "active"
    subscription.reference = upgrade.payment_reference or upgrade.reference
    subscription.authorization_code = upgrade.new_authorization_code or authorization_code
    subscription.paystack_subscription_code = upgrade.new_subscription_code
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = False
    subscription.paystack_email_token = target_data.get("email_token") or subscription.paystack_email_token
    subscription.last_event = "subscription.upgrade.completed"
    subscription.updated_at = now_utc()

    metadata = get_metadata(subscription)
    metadata.update({
        "plan": upgrade.new_plan,
        "interval": upgrade.new_interval,
        "recurring": True,
        "payment_channel": payment_channel or "unknown",
        "last_payment_reference": upgrade.payment_reference or upgrade.reference,
        "old_subscription_code": upgrade.old_subscription_code,
        "upgrade_completed": True,
        "upgrade_first_debit": upgrade.first_debit.isoformat(),
        "upgrade_credit_kobo": upgrade.unused_value_kobo,
        "upgrade_amount_kobo": upgrade.upgrade_amount_kobo,
        "upgrade_old_subscription_status": str(old_data.get("status") or "cancelled").lower(),
    })
    for key in ("pending_plan", "pending_interval", "pending_upgrade_reference", "pending_upgrade_subscription_code", "upgrade_cleanup_pending", "upgrade_amount", "upgrade", "previous_authorization_code"):
        metadata.pop(key, None)
    set_metadata(subscription, metadata)

    user.plan = upgrade.new_plan
    user.subscription_status = "active"
    user.subscription_ends_at = period_end

    upgrade.payment_amount_kobo = payment_amount_kobo or upgrade.payment_amount_kobo
    upgrade.payment_channel = payment_channel or upgrade.payment_channel
    upgrade.status = "completed"
    upgrade.last_error = None
    upgrade.completed_at = now_utc()
    upgrade.updated_at = now_utc()

    await record_upgrade_payment(db, upgrade, user, payment_amount_kobo, payment_channel, paid_at)
    await db.commit()

    return {"status": "success", "payment_method": "recurring", "payment_channel": payment_channel or "unknown", "plan": upgrade.new_plan, "interval": upgrade.new_interval, "subscription_status": user.subscription_status, "subscription_ends_at": period_end, "reference": upgrade.payment_reference or upgrade.reference, "subscription_code": upgrade.new_subscription_code, "old_subscription_code": upgrade.old_subscription_code, "old_subscription_status": str(old_data.get("status") or "cancelled").lower(), "credit_applied": upgrade.unused_value_kobo / 100, "upgrade_amount": upgrade.upgrade_amount_kobo / 100, "first_debit": upgrade.first_debit}


async def complete_one_time_upgrade(db: AsyncSession, user: DBUser, subscription: DBSubscription, upgrade: DBSubscriptionUpgrade, *, payment_channel: str, paid_at: datetime | None = None, payment_amount_kobo: int = 0) -> dict:
    """Upgrade path for users without a Paystack recurring subscription: no subscription
    object to create/disable at Paystack, just move the local plan/period forward."""
    if upgrade.status == "completed":
        return {"status": "success", "plan": upgrade.new_plan, "interval": upgrade.new_interval, "reference": upgrade.payment_reference or upgrade.reference, "first_debit": upgrade.first_debit}

    paid_at = paid_at or now_utc()
    period_end = upgrade.first_debit

    subscription.plan = upgrade.new_plan
    subscription.status = "active"
    subscription.reference = upgrade.payment_reference or upgrade.reference
    subscription.current_period_start = paid_at
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = False
    subscription.last_event = "subscription.upgrade.completed"
    subscription.updated_at = now_utc()

    metadata = get_metadata(subscription)
    metadata.update({"plan": upgrade.new_plan, "interval": upgrade.new_interval, "recurring": False, "payment_channel": payment_channel or "unknown", "last_payment_reference": upgrade.payment_reference or upgrade.reference, "upgrade_completed": True, "upgrade_first_debit": upgrade.first_debit.isoformat(), "upgrade_credit_kobo": upgrade.unused_value_kobo, "upgrade_amount_kobo": upgrade.upgrade_amount_kobo})
    for key in ("pending_plan", "pending_interval", "pending_upgrade_reference", "upgrade_amount", "upgrade"):
        metadata.pop(key, None)
    set_metadata(subscription, metadata)

    user.plan = upgrade.new_plan
    user.subscription_status = "active"
    user.subscription_ends_at = period_end

    upgrade.payment_amount_kobo = payment_amount_kobo or upgrade.payment_amount_kobo
    upgrade.payment_channel = payment_channel or upgrade.payment_channel
    upgrade.status = "completed"
    upgrade.last_error = None
    upgrade.completed_at = now_utc()
    upgrade.updated_at = now_utc()

    await record_upgrade_payment(db, upgrade, user, payment_amount_kobo, payment_channel, paid_at)
    await db.commit()

    return {"status": "success", "payment_method": "one_time", "payment_channel": payment_channel or "unknown", "plan": upgrade.new_plan, "interval": upgrade.new_interval, "subscription_status": user.subscription_status, "subscription_ends_at": period_end, "reference": upgrade.payment_reference or upgrade.reference, "credit_applied": upgrade.unused_value_kobo / 100, "upgrade_amount": upgrade.upgrade_amount_kobo / 100}
