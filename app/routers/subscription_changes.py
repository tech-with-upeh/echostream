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


@router.post("/change-plan")
async def change_subscription_plan(
    plan: str,
    interval: str,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Switch an existing paid subscription to another Paystack plan.

    Paystack doesn't expose a direct "move this subscription to another
    plan" endpoint. We therefore create the replacement subscription with
    the existing reusable authorization and schedule its first debit for the
    end of the current billing period, then disable the old subscription.

    EchoStream keeps the current plan active locally until that period ends.
    """
    plan = plan.strip().lower()
    interval = interval.strip().lower()

    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid paid subscription plan")

    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid billing interval. Use month or year.")

    subscription = current_user.subscription
    if not subscription:
        raise HTTPException(status_code=400, detail="No subscription found")

    if subscription.status not in {"active", "non_renewing"}:
        raise HTTPException(status_code=400, detail="Your subscription is not active")

    # Keep the billing interval in metadata because the DB subscription model
    # intentionally stores the product plan separately from the interval.
    current_interval = None
    if subscription.metadata_json:
        try:
            current_interval = json.loads(subscription.metadata_json).get("interval")
        except json.JSONDecodeError:
            current_interval = None

    if current_user.plan == plan and current_interval == interval:
        raise HTTPException(status_code=400, detail="You are already on this plan and billing interval")

    if not subscription.paystack_customer_code:
        raise HTTPException(status_code=400, detail="Paystack customer information is missing")

    if not subscription.authorization_code:
        raise HTTPException(
            status_code=400,
            detail="Your current payment authorization cannot be reused. Please use normal checkout.",
        )

    # Always refresh from Paystack before changing anything so the local
    # period-end value is not stale.
    if not subscription.paystack_subscription_code:
        raise HTTPException(status_code=400, detail="Paystack subscription code is missing")

    try:
        existing_result = await fetch_subscription(subscription.paystack_subscription_code)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    existing_data = existing_result.get("data") or {}
    period_end_raw = existing_data.get("next_payment_date")
    period_end = parse_datetime(period_end_raw)

    if not period_end:
        raise HTTPException(
            status_code=400,
            detail="Could not determine the current subscription end date from Paystack",
        )

    # Prevent accidentally creating another replacement subscription if the
    # endpoint is retried after a successful create.
    pending = {}
    if subscription.metadata_json:
        try:
            pending = json.loads(subscription.metadata_json)
        except json.JSONDecodeError:
            pending = {}

    if (
        pending.get("pending_plan") == plan
        and pending.get("pending_interval") == interval
        and pending.get("pending_subscription_code")
    ):
        return {
            "status": "already_scheduled",
            "current_plan": current_user.plan,
            "current_interval": current_interval,
            "current_subscription_ends_at": current_user.subscription_ends_at,
            "new_plan": plan,
            "new_interval": interval,
            "new_subscription_code": pending["pending_subscription_code"],
            "starts_at": pending.get("pending_start_date"),
        }

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

    # Disable the old recurring subscription so it cannot charge again. The
    # new subscription is already scheduled for the current period end.
    try:
        await disable_subscription(
            subscription.paystack_subscription_code,
            subscription.paystack_email_token or "",
        )
    except PaystackError as exc:
        # The new subscription exists, but the old one could not be disabled.
        # Do not silently claim the switch succeeded because that could cause
        # a duplicate charge. Store the pending code so the operation can be
        # retried safely.
        pending.update({
            "pending_plan": plan,
            "pending_interval": interval,
            "pending_subscription_code": new_code,
            "pending_start_date": start_date,
            "old_subscription_code": subscription.paystack_subscription_code,
        })
        subscription.metadata_json = json.dumps(pending)
        subscription.last_event = "subscription.change_pending_disable"
        subscription.updated_at = now_utc()
        db.commit()
        raise HTTPException(
            status_code=502,
            detail=(
                "Replacement subscription was created, but the old subscription "
                f"could not be disabled: {exc}"
            ),
        ) from exc

    pending.update({
        "pending_plan": plan,
        "pending_interval": interval,
        "pending_subscription_code": new_code,
        "pending_start_date": start_date,
        "old_subscription_code": subscription.paystack_subscription_code,
    })

    # Do NOT change current_user.plan yet. The current subscription remains
    # active locally until its existing paid period ends.
    subscription.metadata_json = json.dumps(pending)
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
        "message": "The current plan remains active until the current billing period ends. The new plan starts afterward.",
    }
