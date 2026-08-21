import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    create_subscription,
    disable_subscription,
    fetch_subscription,
    get_plan_code,
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


@router.post("/change-plan")
async def change_subscription_plan(
    plan: str,
    interval: str,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = plan.strip().lower()
    interval = interval.strip().lower()

    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid paid subscription plan")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid billing interval. Use month or year.")

    subscription = current_user.subscription
    if not subscription or subscription.status not in {"active", "non_renewing"}:
        raise HTTPException(status_code=400, detail="You do not have an active paid subscription to change.")

    metadata = get_metadata(subscription)
    current_interval = metadata.get("interval")
    if current_user.plan == plan and current_interval == interval:
        raise HTTPException(status_code=400, detail="You are already on this plan and billing interval")

    if not subscription.paystack_customer_code:
        raise HTTPException(status_code=400, detail="Paystack customer information is missing")
    if not subscription.authorization_code:
        raise HTTPException(status_code=400, detail="Your current payment authorization cannot be reused. Please use normal checkout.")
    if not subscription.paystack_subscription_code:
        raise HTTPException(status_code=400, detail="Paystack subscription code is missing")

    # Idempotency: if a replacement is already scheduled, return it rather
    # than creating another subscription.
    if metadata.get("pending_subscription_code"):
        if metadata.get("pending_plan") == plan and metadata.get("pending_interval") == interval:
            return {
                "status": "already_scheduled",
                "current_plan": current_user.plan,
                "current_interval": current_interval,
                "current_subscription_ends_at": current_user.subscription_ends_at,
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

    # Do not change the user's plan yet. First disable the old recurring debit.
    # The replacement is scheduled for the end of the current period.
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
        "current_plan": current_user.plan,
        "current_interval": current_interval,
        "current_subscription_ends_at": current_user.subscription_ends_at,
        "new_plan": plan,
        "new_interval": interval,
        "new_subscription_code": new_code,
        "starts_at": start_date,
        "message": "Your current subscription remains active until its current period ends. The new plan will be activated after its first successful charge.",
    }
