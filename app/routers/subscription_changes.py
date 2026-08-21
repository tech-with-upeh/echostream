import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

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
    db: Session = Depends(get_db),
):
    """Change a paid plan.

    If the existing payment has a reusable authorization (normally card),
    schedule a Paystack subscription replacement. If it does not (for
    example a bank transfer), create a fresh checkout instead and only switch
    the local plan after that payment is verified.
    """
    plan = plan.strip().lower()
    interval = interval.strip().lower()

    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid paid subscription plan")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid billing interval. Use month or year.")

    subscription = current_user.subscription
    if not subscription:
        raise HTTPException(status_code=400, detail="No subscription record found")

    metadata = get_metadata(subscription)
    current_interval = metadata.get("interval")
    recurring = bool(metadata.get("recurring", bool(subscription.authorization_code)))

    if current_user.plan == plan and current_interval == interval:
        raise HTTPException(status_code=400, detail="You are already on this plan and billing interval")

    # ---------------------------------------------------------------
    # Non-recurring payment: fresh checkout.
    # ---------------------------------------------------------------
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
                metadata={
                    "user_id": current_user.id,
                    "plan": plan,
                    "interval": interval,
                    "purpose": "plan_change",
                    "recurring": False,
                },
            )
        except PaystackError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        data = result.get("data") or {}
        reference = data.get("reference") or reference
        metadata.update({
            "pending_plan": plan,
            "pending_interval": interval,
            "pending_change_reference": reference,
            "pending_change_recurring": False,
        })
        subscription.metadata_json = json.dumps(metadata)
        subscription.last_event = "subscription.change.payment_pending"
        subscription.updated_at = now_utc()
        db.commit()

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
            "message": "Complete the new payment. Your current plan remains active until the new payment succeeds.",
        }

    # ---------------------------------------------------------------
    # Recurring payment: schedule replacement subscription.
    # ---------------------------------------------------------------
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
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    existing_data = existing_result.get("data") or {}
    period_end = parse_datetime(existing_data.get("next_payment_date"))
    if not period_end:
        raise HTTPException(status_code=400, detail="Could not determine the current subscription end date from Paystack")

    start_date = period_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    try:
        new_result = await create_subscription(
            customer=subscription.paystack_customer_code,
            plan_code=get_plan_code(plan, interval),
            authorization_code=subscription.authorization_code,
            start_date=start_date,
        )
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    new_data = new_result.get("data") or {}
    new_code = new_data.get("subscription_code")
    if not new_code:
        raise HTTPException(status_code=502, detail="Paystack did not return the replacement subscription code")

    try:
        await disable_subscription(
            subscription.paystack_subscription_code,
            subscription.paystack_email_token or "",
        )
    except PaystackError as exc:
        metadata.update({
            "pending_plan": plan,
            "pending_interval": interval,
            "pending_subscription_code": new_code,
            "pending_start_date": start_date,
            "old_subscription_code": subscription.paystack_subscription_code,
        })
        subscription.metadata_json = json.dumps(metadata)
        subscription.last_event = "subscription.change_pending_disable"
        subscription.updated_at = now_utc()
        db.commit()
        raise HTTPException(status_code=502, detail=f"Replacement subscription was created, but the old subscription could not be disabled: {exc}") from exc

    metadata.update({
        "pending_plan": plan,
        "pending_interval": interval,
        "pending_subscription_code": new_code,
        "pending_start_date": start_date,
        "old_subscription_code": subscription.paystack_subscription_code,
    })
    subscription.metadata_json = json.dumps(metadata)
    subscription.cancel_at_period_end = True
    subscription.status = "non_renewing"
    subscription.last_event = "subscription.change_scheduled"
    subscription.updated_at = now_utc()
    db.commit()

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
        "message": "Your current plan remains active until the current period ends. The new recurring plan will be activated after its first successful charge.",
    }


@router.get("/verify-nonrecurring/{reference}")
async def verify_nonrecurring_payment(
    reference: str,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify a bank-transfer/non-recurring plan purchase or plan change."""
    subscription = db.query(DBSubscription).filter(
        DBSubscription.reference == reference,
        DBSubscription.user_id == current_user.id,
    ).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Payment reference not found")

    metadata = get_metadata(subscription)
    pending_reference = metadata.get("pending_change_reference")

    try:
        result = await verify_transaction(reference)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = result.get("data") or {}
    if data.get("status") != "success":
        return {"status": data.get("status", "failed"), "reference": reference}

    payment_plan = metadata.get("pending_plan") or subscription.plan
    payment_interval = metadata.get("pending_interval") or metadata.get("interval", "month")
    purpose = metadata.get("purpose")

    if payment_plan not in PAID_PLANS or payment_interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Payment metadata is invalid")

    authorization = data.get("authorization") or {}
    customer = data.get("customer") or {}
    authorization_code = authorization.get("authorization_code")

    # A payment with no reusable authorization is treated as a fixed-term
    # purchase. If Paystack did provide a reusable authorization, preserve it
    # so future payments can use the recurring flow.
    channel = str(data.get("channel") or "").lower()
    recurring = bool(authorization_code)
    if channel in {"bank", "bank_transfer"} and not authorization_code:
        recurring = False

    paid_at = parse_datetime(data.get("paid_at")) or now_utc()
    ends_at = add_billing_period(paid_at, payment_interval)

    if purpose == "plan_change" or pending_reference == reference:
        subscription.plan = payment_plan
        metadata["interval"] = payment_interval
        metadata.pop("pending_plan", None)
        metadata.pop("pending_interval", None)
        metadata.pop("pending_change_reference", None)
        metadata.pop("pending_change_recurring", None)
    else:
        subscription.plan = payment_plan
        metadata["interval"] = payment_interval

    metadata["recurring"] = recurring
    metadata["payment_channel"] = channel or "unknown"
    metadata["last_payment_reference"] = reference
    set_metadata(subscription, metadata)

    subscription.status = "active"
    subscription.reference = reference
    subscription.authorization_code = authorization_code
    subscription.paystack_customer_code = customer.get("customer_code")
    subscription.paystack_subscription_code = data.get("subscription_code") if recurring else None
    subscription.current_period_start = paid_at
    subscription.current_period_end = ends_at
    subscription.cancel_at_period_end = not recurring
    subscription.last_event = "transaction.verify.nonrecurring" if not recurring else "transaction.verify.recurring"
    subscription.updated_at = now_utc()

    current_user.plan = payment_plan
    current_user.subscription_status = "active"
    current_user.subscription_ends_at = ends_at

    db.commit()

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
