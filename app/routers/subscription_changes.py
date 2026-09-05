import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    create_subscription,
    disable_subscription,
    fetch_plan,
    fetch_subscription,
    get_plan_code,
    initialize_transaction,
    verify_transaction,
)

router = APIRouter(prefix="/payments", tags=["Payments"])
PAID_PLANS = {"essential", "pro"}
VALID_INTERVALS = {"month", "year"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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


async def get_user_subscription(db: AsyncSession, user_id: int) -> DBSubscription | None:
    result = await db.execute(select(DBSubscription).where(DBSubscription.user_id == user_id))
    return result.scalar_one_or_none()


async def get_upgrade_context(db: AsyncSession, current_user: DBUser, plan: str, interval: str):
    plan = plan.strip().lower()
    interval = interval.strip().lower()
    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid paid subscription plan")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid billing interval. Use month or year.")

    subscription = await get_user_subscription(db, current_user.id)
    if not subscription:
        raise HTTPException(status_code=400, detail="No subscription record found")

    metadata = get_metadata(subscription)
    current_plan = str(current_user.plan or subscription.plan or "").strip().lower()
    current_interval = str(metadata.get("interval") or "").strip().lower()
    recurring = bool(metadata.get("recurring", bool(subscription.authorization_code)))

    if current_plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Only paid subscriptions can be upgraded")
    if current_interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Current subscription billing interval is unavailable")
    if not recurring or not subscription.authorization_code or not subscription.paystack_subscription_code:
        raise HTTPException(status_code=400, detail="An active recurring subscription is required for an upgrade")
    if current_plan == plan and current_interval == interval:
        raise HTTPException(status_code=400, detail="You are already on this plan and billing interval")

    try:
        current_plan_data = await fetch_plan(get_plan_code(current_plan, current_interval))
        target_plan_data = await fetch_plan(get_plan_code(plan, interval))
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    current_price_kobo = int((current_plan_data.get("data") or {}).get("amount") or 0)
    target_price_kobo = int((target_plan_data.get("data") or {}).get("amount") or 0)
    if current_price_kobo <= 0 or target_price_kobo <= 0:
        raise HTTPException(status_code=502, detail="Could not determine subscription prices from Paystack")
    if target_price_kobo <= current_price_kobo:
        raise HTTPException(status_code=400, detail="The selected subscription is not an upgrade")

    try:
        current_remote = await fetch_subscription(subscription.paystack_subscription_code)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    remote_data = current_remote.get("data") or {}
    period_start = parse_datetime(remote_data.get("start")) or subscription.current_period_start
    period_end = parse_datetime(remote_data.get("next_payment_date")) or subscription.current_period_end
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="Could not determine the current billing period")

    period_start = period_start.astimezone(timezone.utc)
    period_end = period_end.astimezone(timezone.utc)
    now = now_utc()
    if period_end <= now:
        raise HTTPException(status_code=400, detail="The current subscription period has ended")

    total_days = Decimal(str((period_end - period_start).total_seconds())) / Decimal("86400")
    remaining_days = Decimal(str((period_end - now).total_seconds())) / Decimal("86400")
    if total_days <= 0:
        raise HTTPException(status_code=400, detail="Invalid current billing period")
    if remaining_days < 0:
        remaining_days = Decimal("0")

    current_price_naira = Decimal(current_price_kobo) / Decimal("100")
    target_price_naira = Decimal(target_price_kobo) / Decimal("100")
    unused_value = current_price_naira * remaining_days / total_days
    upgrade_amount = target_price_naira - unused_value
    if upgrade_amount < 0:
        upgrade_amount = Decimal("0")

    upgrade_amount_kobo = int((upgrade_amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    unused_value_kobo = int((unused_value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return {
        "subscription": subscription,
        "metadata": metadata,
        "current_plan": current_plan,
        "current_interval": current_interval,
        "new_plan": plan,
        "new_interval": interval,
        "period_start": period_start,
        "period_end": period_end,
        "total_days": float(total_days),
        "remaining_days": float(remaining_days),
        "current_plan_price": float(current_price_naira),
        "new_plan_price": float(target_price_naira),
        "unused_value": float(unused_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "unused_value_kobo": unused_value_kobo,
        "upgrade_amount": float(Decimal(upgrade_amount_kobo) / Decimal("100")),
        "upgrade_amount_kobo": upgrade_amount_kobo,
    }


@router.post("/upgrade/quote")
async def upgrade_quote(
    plan: str,
    interval: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context = await get_upgrade_context(db, current_user, plan, interval)
    return {
        "current_plan": context["current_plan"],
        "current_interval": context["current_interval"],
        "new_plan": context["new_plan"],
        "new_interval": context["new_interval"],
        "currency": "NGN",
        "current_plan_price": context["current_plan_price"],
        "new_plan_price": context["new_plan_price"],
        "billing_interval": context["new_interval"],
        "current_period_start": context["period_start"],
        "current_period_ends_at": context["period_end"],
        "total_days": context["total_days"],
        "remaining_days": context["remaining_days"],
        "unused_value": context["unused_value"],
        "upgrade_amount": context["upgrade_amount"],
    }


@router.post("/upgrade")
async def upgrade_subscription(
    plan: str,
    interval: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context = await get_upgrade_context(db, current_user, plan, interval)
    subscription = context["subscription"]
    metadata = context["metadata"]

    pending_reference = metadata.get("pending_upgrade_reference")
    if pending_reference:
        return {
            "status": "already_pending",
            "current_plan": context["current_plan"],
            "current_interval": context["current_interval"],
            "new_plan": context["new_plan"],
            "new_interval": context["new_interval"],
            "reference": pending_reference,
        }

    reference = f"echostream_upgrade_{current_user.id}_{now_utc().strftime('%Y%m%d%H%M%S%f')}"
    try:
        # Upgrade payment is intentionally a one-time charge. Passing a Paystack
        # plan here would make Paystack use the plan amount instead of our
        # server-calculated prorated amount. The recurring target subscription
        # is created only after this payment succeeds.
        result = await initialize_transaction(
            email=current_user.email,
            reference=reference,
            callback_url=settings.PAYSTACK_CALLBACK_URL,
            metadata={
                "user_id": current_user.id,
                "plan": context["new_plan"],
                "interval": context["new_interval"],
                "purpose": "new_subscription",
                "upgrade": True,
                "previous_plan": context["current_plan"],
                "previous_interval": context["current_interval"],
                "previous_subscription_code": subscription.paystack_subscription_code,
                "unused_value": context["unused_value"],
                "upgrade_amount": context["upgrade_amount"],
            },
            amount_kobo=context["upgrade_amount_kobo"],
        )
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = result.get("data") or {}
    reference = data.get("reference") or reference
    metadata.update({
        "pending_plan": context["new_plan"],
        "pending_interval": context["new_interval"],
        "pending_upgrade_reference": reference,
        "upgrade": True,
        "upgrade_amount": context["upgrade_amount"],
        "upgrade_amount_kobo": context["upgrade_amount_kobo"],
        "previous_plan": context["current_plan"],
        "previous_interval": context["current_interval"],
        "previous_subscription_code": subscription.paystack_subscription_code,
        "previous_authorization_code": subscription.authorization_code,
    })
    set_metadata(subscription, metadata)
    subscription.reference = reference
    subscription.last_event = "subscription.upgrade.payment_pending"
    subscription.updated_at = now_utc()
    await db.commit()

    return {
        "status": "payment_required",
        "current_plan": context["current_plan"],
        "current_interval": context["current_interval"],
        "new_plan": context["new_plan"],
        "new_interval": context["new_interval"],
        "upgrade_amount": context["upgrade_amount"],
        "currency": "NGN",
        "reference": reference,
        "authorization_url": data.get("authorization_url"),
        "access_code": data.get("access_code"),
    }


@router.post("/change-plan")
async def change_subscription_plan(
    plan: str,
    interval: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = plan.strip().lower()
    interval = interval.strip().lower()

    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid paid subscription plan")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid billing interval. Use month or year.")

    result = await db.execute(select(DBSubscription).where(DBSubscription.user_id == current_user.id))
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=400, detail="No subscription record found")

    metadata = get_metadata(subscription)
    current_interval = metadata.get("interval")
    recurring = bool(metadata.get("recurring", bool(subscription.authorization_code)))

    if current_user.plan == plan and current_interval == interval:
        raise HTTPException(status_code=400, detail="You are already on this plan and billing interval")

    if not recurring or not subscription.authorization_code:
        pending_reference = metadata.get("pending_change_reference")
        if pending_reference:
            return {
                "status": "already_pending",
                "payment_method": "non_recurring",
                "reference": pending_reference,
                "new_plan": metadata.get("pending_plan", plan),
                "new_interval": metadata.get("pending_interval", interval),
            }

        reference = f"echostream_change_{current_user.id}_{now_utc().strftime('%Y%m%d%H%M%S%f')}"
        try:
            result = await initialize_transaction(
                email=current_user.email,
                plan_code=get_plan_code(plan, interval),
                reference=reference,
                callback_url=settings.PAYSTACK_CALLBACK_URL,
                metadata={"user_id": current_user.id, "plan": plan, "interval": interval, "purpose": "plan_change"},
            )
        except PaystackError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        data = result.get("data") or {}
        reference = data.get("reference") or reference
        metadata.update({"pending_plan": plan, "pending_interval": interval, "pending_change_reference": reference})
        set_metadata(subscription, metadata)
        subscription.last_event = "subscription.change.payment_pending"
        subscription.updated_at = now_utc()
        await db.commit()

        return {
            "status": "payment_required",
            "payment_method": "non_recurring",
            "current_plan": current_user.plan,
            "current_interval": current_interval,
            "new_plan": plan,
            "new_interval": interval,
            "reference": reference,
            "authorization_url": data.get("authorization_url"),
            "access_code": data.get("access_code"),
        }

    if not subscription.paystack_customer_code:
        raise HTTPException(status_code=400, detail="Paystack customer information is missing")
    if not subscription.paystack_subscription_code:
        raise HTTPException(status_code=400, detail="Paystack subscription code is missing")

    if metadata.get("pending_subscription_code"):
        if metadata.get("pending_plan") == plan and metadata.get("pending_interval") == interval:
            return {
                "status": "already_scheduled",
                "payment_method": "recurring",
                "current_plan": current_user.plan,
                "current_interval": current_interval,
                "new_plan": plan,
                "new_interval": interval,
                "new_subscription_code": metadata["pending_subscription_code"],
                "starts_at": metadata.get("pending_start_date"),
            }
        raise HTTPException(status_code=409, detail="A different subscription change is already scheduled.")

    old_subscription_code = subscription.paystack_subscription_code
    try:
        existing_result = await fetch_subscription(old_subscription_code)
        period_end = parse_datetime((existing_result.get("data") or {}).get("next_payment_date"))
        if not period_end:
            raise PaystackError("Could not determine the current subscription end date from Paystack")

        start_date = period_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        new_result = await create_subscription(
            customer=subscription.paystack_customer_code,
            plan_code=get_plan_code(plan, interval),
            authorization_code=subscription.authorization_code,
            start_date=start_date,
        )
        new_code = (new_result.get("data") or {}).get("subscription_code")
        if not new_code:
            raise PaystackError("Paystack did not return the replacement subscription code")
        await disable_subscription(old_subscription_code, subscription.paystack_email_token or "")
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    metadata.update({
        "pending_plan": plan,
        "pending_interval": interval,
        "pending_subscription_code": new_code,
        "pending_start_date": start_date,
        "old_subscription_code": old_subscription_code,
    })
    set_metadata(subscription, metadata)
    subscription.cancel_at_period_end = True
    subscription.status = "non_renewing"
    subscription.last_event = "subscription.change_scheduled"
    subscription.updated_at = now_utc()
    await db.commit()

    return {
        "status": "scheduled",
        "payment_method": "recurring",
        "current_plan": current_user.plan,
        "current_interval": current_interval,
        "current_subscription_ends_at": current_user.subscription_ends_at,
        "new_plan": plan,
        "new_interval": interval,
        "new_subscription_code": new_code,
        "starts_at": start_date,
    }


@router.get("/verify/{reference}")
async def verify_payment(
    reference: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DBSubscription).where(
            DBSubscription.user_id == current_user.id,
            DBSubscription.reference == reference,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        result = await db.execute(
            select(DBSubscription).where(
                DBSubscription.user_id == current_user.id,
                DBSubscription.metadata_json.like(f'%\"pending_change_reference\": \"{reference}\"%'),
            )
        )
        subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=404, detail="Payment reference not found")

    try:
        result = await verify_transaction(reference)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = result.get("data") or {}
    if data.get("status") != "success":
        return {"status": data.get("status", "failed"), "reference": reference}

    metadata = get_metadata(subscription)
    is_upgrade = bool(metadata.get("upgrade") and metadata.get("pending_upgrade_reference") == reference)
    payment_plan = metadata.get("pending_plan") or metadata.get("plan") or subscription.plan
    payment_interval = metadata.get("pending_interval") or metadata.get("interval") or "month"

    if payment_plan not in PAID_PLANS or payment_interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Payment metadata is invalid")

    authorization = data.get("authorization") or {}
    customer = data.get("customer") or {}
    authorization_code = authorization.get("authorization_code")
    channel = str(data.get("channel") or "").lower()
    paid_at = parse_datetime(data.get("paid_at")) or now_utc()

    # Upgrade payments are deliberately one-time. After Paystack confirms the
    # prorated charge, create the new recurring subscription with the new
    # authorization, then disable the old subscription. We persist the new
    # subscription code before disabling the old one so a retry can finish the
    # operation safely if the request is interrupted.
    if is_upgrade:
        if not authorization_code:
            raise HTTPException(status_code=502, detail="Upgrade payment did not return a reusable authorization code")
        if not subscription.paystack_customer_code and not customer.get("customer_code"):
            raise HTTPException(status_code=400, detail="Paystack customer information is missing")

        old_subscription_code = metadata.get("previous_subscription_code") or subscription.paystack_subscription_code
        if not old_subscription_code:
            raise HTTPException(status_code=400, detail="Previous Paystack subscription code is missing")

        new_subscription_code = metadata.get("pending_upgrade_subscription_code")
        if not new_subscription_code:
            customer_code = subscription.paystack_customer_code or customer.get("customer_code")
            try:
                new_result = await create_subscription(
                    customer=customer_code,
                    plan_code=get_plan_code(payment_plan, payment_interval),
                    authorization_code=authorization_code,
                )
                new_subscription_code = (new_result.get("data") or {}).get("subscription_code")
                if not new_subscription_code:
                    raise PaystackError("Paystack did not return the new subscription code")
            except PaystackError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            metadata["pending_upgrade_subscription_code"] = new_subscription_code
            metadata["upgrade_payment_authorization_code"] = authorization_code
            set_metadata(subscription, metadata)
            await db.commit()

        # The old subscription is disabled only after the upgrade payment has
        # succeeded and the replacement subscription exists.
        try:
            await disable_subscription(old_subscription_code, subscription.paystack_email_token or "")
        except PaystackError as exc:
            metadata["upgrade_cleanup_pending"] = True
            metadata["old_subscription_code"] = old_subscription_code
            metadata["pending_upgrade_subscription_code"] = new_subscription_code
            set_metadata(subscription, metadata)
            subscription.last_event = "subscription.upgrade.old_subscription_disable_pending"
            subscription.updated_at = now_utc()
            await db.commit()
            raise HTTPException(
                status_code=502,
                detail="Upgrade succeeded, but the previous subscription could not be disabled. Retry verification to finish cleanup.",
            ) from exc

        try:
            new_remote = await fetch_subscription(new_subscription_code)
            new_remote_data = new_remote.get("data") or {}
            period_start = parse_datetime(new_remote_data.get("start")) or paid_at
            period_end = parse_datetime(new_remote_data.get("next_payment_date"))
        except PaystackError:
            period_start = paid_at
            period_end = None

        if not period_end:
            period_end = add_billing_period(period_start, payment_interval)

        subscription.plan = payment_plan
        subscription.status = "active"
        subscription.reference = reference
        subscription.authorization_code = authorization_code
        subscription.paystack_customer_code = subscription.paystack_customer_code or customer.get("customer_code")
        subscription.paystack_subscription_code = new_subscription_code
        subscription.current_period_start = period_start
        subscription.current_period_end = period_end
        subscription.cancel_at_period_end = False
        subscription.last_event = "subscription.upgrade.completed"
        subscription.updated_at = now_utc()

        metadata["interval"] = payment_interval
        metadata["recurring"] = True
        metadata["payment_channel"] = channel or "unknown"
        metadata["last_payment_reference"] = reference
        metadata["old_subscription_code"] = old_subscription_code
        metadata["previous_plan"] = metadata.get("previous_plan")
        metadata["previous_interval"] = metadata.get("previous_interval")
        metadata["upgrade_completed"] = True
        metadata.pop("pending_plan", None)
        metadata.pop("pending_interval", None)
        metadata.pop("pending_upgrade_reference", None)
        metadata.pop("pending_upgrade_subscription_code", None)
        metadata.pop("upgrade_cleanup_pending", None)
        metadata.pop("upgrade_amount", None)
        metadata.pop("upgrade_amount_kobo", None)
        metadata.pop("upgrade", None)
        set_metadata(subscription, metadata)

        current_user.plan = payment_plan
        current_user.subscription_status = "active"
        current_user.subscription_ends_at = period_end
        await db.commit()

        return {
            "status": "success",
            "payment_method": "recurring",
            "payment_channel": channel or "unknown",
            "plan": payment_plan,
            "interval": payment_interval,
            "subscription_status": current_user.subscription_status,
            "subscription_ends_at": current_user.subscription_ends_at,
            "reference": reference,
            "subscription_code": new_subscription_code,
            "old_subscription_code": old_subscription_code,
        }

    authorization_code = authorization.get("authorization_code")
    recurring = bool(authorization_code) and bool(data.get("subscription_code"))

    if recurring:
        subscription_code = data.get("subscription_code")
        try:
            remote = await fetch_subscription(subscription_code)
            remote_data = remote.get("data") or {}
            period_start = parse_datetime(remote_data.get("start")) or paid_at
            period_end = parse_datetime(remote_data.get("next_payment_date"))
        except PaystackError:
            period_start = paid_at
            period_end = None
    else:
        period_start = paid_at
        period_end = add_billing_period(paid_at, payment_interval)

    if not period_end:
        period_end = add_billing_period(period_start, payment_interval)

    subscription.plan = payment_plan
    subscription.status = "active"
    subscription.reference = reference
    subscription.authorization_code = authorization_code
    subscription.paystack_customer_code = customer.get("customer_code")
    subscription.paystack_subscription_code = data.get("subscription_code") if recurring else None
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = not recurring
    subscription.last_event = "transaction.verify.recurring" if recurring else "transaction.verify.one_time"
    subscription.updated_at = now_utc()

    metadata["interval"] = payment_interval
    metadata["recurring"] = recurring
    metadata["payment_channel"] = channel or "unknown"
    metadata["last_payment_reference"] = reference
    metadata.pop("pending_plan", None)
    metadata.pop("pending_interval", None)
    metadata.pop("pending_change_reference", None)
    metadata.pop("pending_upgrade_reference", None)
    metadata.pop("upgrade_amount", None)
    metadata.pop("upgrade_amount_kobo", None)
    metadata.pop("previous_plan", None)
    metadata.pop("previous_interval", None)
    set_metadata(subscription, metadata)

    current_user.plan = payment_plan
    current_user.subscription_status = "active"
    current_user.subscription_ends_at = period_end

    await db.commit()

    return {
        "status": "success",
        "payment_method": "recurring" if recurring else "one_time",
        "payment_channel": channel or "unknown",
        "plan": payment_plan,
        "interval": payment_interval,
        "subscription_status": current_user.subscription_status,
        "subscription_ends_at": current_user.subscription_ends_at,
        "reference": reference,
    }
