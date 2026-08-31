import json
from datetime import datetime, timezone

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

    try:
        existing_result = await fetch_subscription(subscription.paystack_subscription_code)
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
        await disable_subscription(subscription.paystack_subscription_code, subscription.paystack_email_token or "")
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    metadata.update({
        "pending_plan": plan,
        "pending_interval": interval,
        "pending_subscription_code": new_code,
        "pending_start_date": start_date,
        "old_subscription_code": subscription.paystack_subscription_code,
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
    """Verify any EchoStream Paystack payment in one endpoint."""
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
                DBSubscription.metadata_json.like(f'%"pending_change_reference": "{reference}"%'),
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
    payment_plan = metadata.get("pending_plan") or metadata.get("plan") or subscription.plan
    payment_interval = metadata.get("pending_interval") or metadata.get("interval") or "month"

    if payment_plan not in PAID_PLANS or payment_interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Payment metadata is invalid")

    authorization = data.get("authorization") or {}
    customer = data.get("customer") or {}
    authorization_code = authorization.get("authorization_code")
    channel = str(data.get("channel") or "").lower()
    recurring = bool(authorization_code) and bool(data.get("subscription_code"))
    paid_at = parse_datetime(data.get("paid_at")) or now_utc()

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
    metadata.pop("pending_change_recurring", None)
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
