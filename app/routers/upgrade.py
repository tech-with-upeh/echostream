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
        # One-time payment plan: no Paystack subscription to read the period from,
        # the billing period we track locally is the source of truth.
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
        # A prior attempt may have already created this subscription at Paystack
        # before our own commit landed. Look for it instead of failing outright.
        existing = await _find_existing_target_subscription(subscription.paystack_customer_code, plan_code)
        if existing:
            return existing
        raise
    print("result:::  ", result)
    data = result.get("data") or {}
    if result.get("message") == "Subscription successfully created":
        data["ispending"] = True
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
        print("upgradeeeee--->:",target_data)
        if target_data.get("ispending"):
            return {"status": "pending", "payment_method": "recurring", "payment_channel": payment_channel or "unknown", "plan": upgrade.new_plan, "interval": upgrade.new_interval, "subscription_status": user.subscription_status, "subscription_ends_at": upgrade.old_period_end, "reference": upgrade.payment_reference or upgrade.reference, "subscription_code": upgrade.new_subscription_code, "old_subscription_code": upgrade.old_subscription_code, "old_subscription_status": "pending", "credit_applied": upgrade.unused_value_kobo / 100, "upgrade_amount": upgrade.upgrade_amount_kobo / 100, "first_debit": upgrade.first_debit}
 
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

    return {"status": "success", "payment_method": "one_time", "payment_channel": payment_channel or "unknown", "plan": upgrade.new_plan, "interval": upgrade.new_interval, "subscription_status": user.subscription_status, "subscription_ends_at": period_end, "reference": upgrade.payment_reference or upgrade.reference, "credit_applied": upgrade.unused_value_kobo / 100, "upgrade_amount": upgrade.upgrade_amount_kobo / 100, "first_debit": upgrade.first_debit}


async def finalize_upgrade_reference(db: AsyncSession, reference: str, user: DBUser) -> dict:
    upgrade = await get_upgrade_by_reference(db, reference, lock=True)
    if not upgrade or upgrade.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment reference not found")
    subscription = await get_user_subscription(db, user.id, lock=True)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if upgrade.status == "completed":
        return {"status": "success", "plan": upgrade.new_plan, "interval": upgrade.new_interval, "subscription_code": upgrade.new_subscription_code, "reference": upgrade.payment_reference or upgrade.reference, "first_debit": upgrade.first_debit}

    if upgrade.upgrade_amount_kobo == 0:
        if not upgrade.old_subscription_code:
            return await complete_one_time_upgrade(db, user, subscription, upgrade, payment_channel=subscription.payment_method or "card")
        return await complete_upgrade(db, user, subscription, upgrade, authorization_code=subscription.authorization_code or upgrade.old_authorization_code or "", payment_channel=subscription.payment_method or "card")

    try:
        payment = await verify_transaction(upgrade.payment_reference or reference)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    data = payment.get("data") or {}
    status_value = str(data.get("status") or "failed").lower()
    if status_value != "success":
        if status_value in {"failed", "abandoned", "reversed"}:
            upgrade.status = "failed"
            upgrade.last_error = f"Paystack payment status: {status_value}"
            upgrade.updated_at = now_utc()
            await db.commit()
        return {"status": status_value, "reference": upgrade.payment_reference or reference}

    paid_at = parse_datetime(data.get("paid_at")) or now_utc()
    amount = int(data.get("amount") or 0)
    channel = str(data.get("channel") or "unknown").lower()

    if not upgrade.old_subscription_code:
        # One-time payer: no reusable authorization/subscription required.
        return await complete_one_time_upgrade(db, user, subscription, upgrade, payment_channel=channel, paid_at=paid_at, payment_amount_kobo=amount)

    authorization = data.get("authorization") or {}
    authorization_code = authorization.get("authorization_code") or upgrade.old_authorization_code
    if not authorization_code:
        raise HTTPException(status_code=502, detail="Upgrade payment did not return a reusable authorization code")
    customer = data.get("customer") or {}
    if customer.get("customer_code"):
        subscription.paystack_customer_code = customer["customer_code"]
    if not subscription.paystack_customer_code:
        raise HTTPException(status_code=400, detail="Paystack customer information is missing")

    upgrade.status = "payment_success"
    upgrade.payment_amount_kobo = amount
    upgrade.payment_channel = channel
    upgrade.updated_at = now_utc()
    await db.commit()

    return await complete_upgrade(db, user, subscription, upgrade, authorization_code=authorization_code, payment_channel=channel, paid_at=paid_at, payment_amount_kobo=amount)


@router.post("/upgrade/quote")
async def upgrade_quote(plan: str, interval: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    print("upgrade")
    context = await get_upgrade_context(db, current_user, plan, interval)
    return {"current_plan": context["current_plan"], "current_interval": context["current_interval"], "new_plan": context["new_plan"], "new_interval": context["new_interval"], "currency": "NGN", "current_plan_price": context["current_plan_price"], "new_plan_price": context["new_plan_price"], "billing_interval": context["new_interval"], "current_period_start": context["period_start"], "current_period_ends_at": context["period_end"], "total_days": context["total_days"], "remaining_days": context["remaining_days"], "unused_value": context["unused_value"], "credit_applied": context["unused_value"], "upgrade_amount": context["upgrade_amount"], "credit_remaining": 0, "first_debit": context["first_debit"]}


@router.post("/upgrade")
async def upgrade_subscription(plan: str, interval: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await get_upgrade_context(db, current_user, plan, interval, lock=True)
    subscription = context["subscription"]
    pending = await get_pending_upgrade(db, current_user.id, lock=True)

    if pending and pending.new_plan == context["new_plan"] and pending.new_interval == context["new_interval"]:
        if pending.status == "completed":
            if not pending.old_subscription_code:
                return await complete_one_time_upgrade(db, current_user, subscription, pending, payment_channel=pending.payment_channel or "card")
            return await complete_upgrade(db, current_user, subscription, pending, authorization_code=pending.new_authorization_code or subscription.authorization_code or "", payment_channel=pending.payment_channel or "card")
        if pending.upgrade_amount_kobo > 0 and pending.payment_reference:
            try:
                payment = await verify_transaction(pending.payment_reference)
                pending_status = str((payment.get("data") or {}).get("status") or "").lower()
            except PaystackError:
                pending_status = "unknown"
            if pending_status == "success":
                return await finalize_upgrade_reference(db, pending.payment_reference, current_user)
            if pending_status not in {"failed", "abandoned", "reversed"}:
                return {"status": "already_pending", "new_plan": pending.new_plan, "new_interval": pending.new_interval, "reference": pending.payment_reference}
            pending.status = "failed"
            pending.last_error = f"Paystack payment status: {pending_status}"
            pending.updated_at = now_utc()
            await db.commit()

    now = now_utc()
    reference = f"echostream_upgrade_{current_user.id}_{now.strftime('%Y%m%d%H%M%S%f')}"
    upgrade = DBSubscriptionUpgrade(
        user_id=current_user.id,
        subscription_id=subscription.id,
        reference=reference,
        old_plan=context["current_plan"],
        old_interval=context["current_interval"],
        old_subscription_code=subscription.paystack_subscription_code,
        old_authorization_code=subscription.authorization_code,
        old_period_start=context["period_start"],
        old_period_end=context["period_end"],
        new_plan=context["new_plan"],
        new_interval=context["new_interval"],
        total_seconds=context["total_seconds"],
        remaining_seconds=context["remaining_seconds"],
        old_plan_price_kobo=context["current_plan_price_kobo"],
        new_plan_price_kobo=context["new_plan_price_kobo"],
        unused_value_kobo=context["unused_value_kobo"],
        upgrade_amount_kobo=context["upgrade_amount_kobo"],
        credit_duration_seconds=context["credit_duration_seconds"],
        first_debit=context["first_debit"],
        status="pending_payment" if context["upgrade_amount_kobo"] > 0 else "creating_subscription",
        created_at=now,
        updated_at=now,
    )
    db.add(upgrade)
    await db.flush()

    if context["upgrade_amount_kobo"] == 0:
        if not context["recurring"]:
            return await complete_one_time_upgrade(db, current_user, subscription, upgrade, payment_channel=subscription.payment_method or "card")
        return await complete_upgrade(db, current_user, subscription, upgrade, authorization_code=subscription.authorization_code or "", payment_channel=subscription.payment_method or "card")

    txn_metadata = {"user_id": current_user.id, "purpose": "upgrade", "upgrade_reference": reference, "plan": context["new_plan"], "interval": context["new_interval"], "previous_plan": context["current_plan"], "previous_interval": context["current_interval"], "previous_subscription_code": subscription.paystack_subscription_code, "unused_value_kobo": context["unused_value_kobo"], "upgrade_amount_kobo": context["upgrade_amount_kobo"], "first_debit": context["first_debit"].isoformat()}
    upgrade.payment_reference = reference
    upgrade.updated_at = now_utc()
    await db.commit()

    # Recurring subscription => we already hold a reusable authorization code.
    # Try to silently debit it first; only fall back to a hosted checkout if the
    # direct charge can't be attempted or Paystack declines it.
    if context["recurring"] and subscription.authorization_code:
        try:
            charge_result = await charge_authorization(
                email=current_user.email,
                authorization_code=subscription.authorization_code,
                reference=reference,
                amount_kobo=context["upgrade_amount_kobo"],
                metadata=txn_metadata,
            )
            charge_data = charge_result.get("data") or {}
            if str(charge_data.get("status") or "").lower() == "success":
                paid_at = parse_datetime(charge_data.get("paid_at")) or now_utc()
                amount = int(charge_data.get("amount") or context["upgrade_amount_kobo"])
                channel = str(charge_data.get("channel") or "card").lower()
                new_auth = (charge_data.get("authorization") or {}).get("authorization_code") or subscription.authorization_code
                upgrade.status = "payment_success"
                upgrade.payment_amount_kobo = amount
                upgrade.payment_channel = channel
                upgrade.updated_at = now_utc()
                await db.commit()
                return await complete_upgrade(db, current_user, subscription, upgrade, authorization_code=new_auth, payment_channel=channel, paid_at=paid_at, payment_amount_kobo=amount)
        except PaystackError:
            pass  # can't silently charge this authorization; fall back to hosted checkout below

    try:
        result = await initialize_transaction(
            email=current_user.email,
            reference=reference,
            callback_url=settings.PAYSTACK_CALLBACK_URL,
            metadata=txn_metadata,
            amount_kobo=context["upgrade_amount_kobo"],
        )
    except PaystackError as exc:
        upgrade.status = "failed"
        upgrade.last_error = str(exc)
        upgrade.updated_at = now_utc()
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = result.get("data") or {}
    upgrade.payment_reference = data.get("reference") or reference
    upgrade.updated_at = now_utc()
    await db.commit()
    return {"status": "payment_required", "current_plan": context["current_plan"], "current_interval": context["current_interval"], "new_plan": context["new_plan"], "new_interval": context["new_interval"], "upgrade_amount": context["upgrade_amount"], "currency": "NGN", "reference": upgrade.payment_reference, "authorization_url": data.get("authorization_url"), "access_code": data.get("access_code"), "first_debit": context["first_debit"], "credit_remaining": 0}


@router.get("/verify/{reference}")
async def verify_upgrade_or_delegate(reference: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    upgrade = await get_upgrade_by_reference(db, reference)
    if upgrade and upgrade.user_id == current_user.id:
        return await finalize_upgrade_reference(db, reference, current_user)
    from app.routers.payment_reconciliation import verify_payment as reconciliation_verify_payment
    return await reconciliation_verify_payment(reference, current_user, db)


@router.get("/callback", include_in_schema=False)
async def upgrade_callback(reference: str | None = None, trxref: str | None = None, db: AsyncSession = Depends(get_db)):
    payment_reference = reference or trxref
    if not payment_reference:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/payment/failed")
    upgrade = await get_upgrade_by_reference(db, payment_reference)
    if not upgrade:
        from app.routers.payment_reconciliation import payment_callback as reconciliation_payment_callback
        return await reconciliation_payment_callback(payment_reference, trxref, db)
    try:
        user_result = await db.execute(select(DBUser).where(DBUser.id == upgrade.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        result = await finalize_upgrade_reference(db, payment_reference, user)
        target = "/payment/success" if result.get("status") == "success" else "/payment/failed"
    except HTTPException:
        target = "/payment/failed"
    return RedirectResponse(url=f"{settings.FRONTEND_URL}{target}?reference={payment_reference}")


@router.post("/webhook", status_code=200)
async def upgrade_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")
    if not verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    event = str(payload.get("event") or "")
    data = payload.get("data") or {}
    reference = data.get("reference")
    if event in {"charge.success", "charge.failed"} and reference:
        upgrade = await get_upgrade_by_reference(db, reference)
        if upgrade:
            user_result = await db.execute(select(DBUser).where(DBUser.id == upgrade.user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            if event == "charge.failed":
                if upgrade.status != "completed":
                    upgrade.status = "failed"
                    upgrade.last_error = "Paystack charge.failed webhook"
                    upgrade.updated_at = now_utc()
                    await db.commit()
                return {"received": True}
            await finalize_upgrade_reference(db, reference, user)
            return {"received": True}

    from app.routers.payment_reconciliation import paystack_webhook as reconciliation_webhook
    return await reconciliation_webhook(request, db)
