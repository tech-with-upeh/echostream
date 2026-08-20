import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    get_plan_code,
    get_subscription_manage_link,
    initialize_transaction,
    verify_transaction,
    verify_webhook_signature,
)

router = APIRouter(prefix="/payments", tags=["Payments"])

VALID_PLANS = {"starter", "essential", "pro"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def apply_subscription_event(db: Session, event: str, data: dict) -> None:
    subscription_code = data.get("subscription_code") or data.get("subscription_code")
    customer = data.get("customer") or {}
    customer_code = customer.get("customer_code") if isinstance(customer, dict) else None
    metadata = data.get("metadata") or {}
    user_id = metadata.get("user_id") if isinstance(metadata, dict) else None

    subscription = None
    if subscription_code:
        subscription = db.query(DBSubscription).filter(
            DBSubscription.paystack_subscription_code == subscription_code
        ).first()

    if not subscription and user_id:
        subscription = db.query(DBSubscription).filter(
            DBSubscription.user_id == int(user_id)
        ).first()

    if not subscription:
        return

    subscription.last_event = event
    subscription.updated_at = now_utc()
    if customer_code:
        subscription.paystack_customer_code = customer_code

    status_map = {
        "subscription.create": "active",
        "charge.success": "active",
        "subscription.not_renew": "non_renewing",
        "subscription.disable": "canceled",
        "subscription.expiring_cards": "active",
    }
    new_status = status_map.get(event)
    if new_status:
        subscription.status = new_status

    user = subscription.user
    if new_status == "active":
        user.subscription_status = "active"
    elif new_status in {"canceled", "non_renewing"}:
        # Keep paid access until the already-paid period ends when possible.
        if subscription.current_period_end and subscription.current_period_end > now_utc():
            user.subscription_status = "active"
        else:
            user.subscription_status = "canceled"

    db.commit()


@router.post("/subscribe")
async def create_subscription_checkout(
    plan: str,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = plan.lower().strip()
    if plan not in VALID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid subscription plan")

    plan_code = get_plan_code(plan)
    reference = f"echostream_{current_user.id}_{uuid.uuid4().hex}"

    try:
        result = await initialize_transaction(
            email=current_user.email,
            plan_code=plan_code,
            reference=reference,
            callback_url=settings.PAYSTACK_CALLBACK_URL,
            metadata={"user_id": current_user.id, "plan": plan},
        )
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    subscription = current_user.subscription
    timestamp = now_utc()
    if not subscription:
        subscription = DBSubscription(
            user_id=current_user.id,
            plan=plan,
            status="pending",
            reference=reference,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(subscription)
    else:
        subscription.plan = plan
        subscription.status = "pending"
        subscription.reference = reference
        subscription.updated_at = timestamp

    db.commit()

    return {
        "authorization_url": result["data"]["authorization_url"],
        "access_code": result["data"].get("access_code"),
        "reference": reference,
        "plan": plan,
    }


@router.get("/verify/{reference}")
async def verify_payment(
    reference: str,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subscription = db.query(DBSubscription).filter(
        DBSubscription.reference == reference,
        DBSubscription.user_id == current_user.id,
    ).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Payment reference not found")

    try:
        result = await verify_transaction(reference)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = result.get("data", {})
    if data.get("status") != "success":
        return {"status": data.get("status", "failed"), "reference": reference}

    subscription.status = "active"
    subscription.authorization_code = (data.get("authorization") or {}).get("authorization_code")
    subscription.paystack_customer_code = (data.get("customer") or {}).get("customer_code")
    subscription.paystack_subscription_code = data.get("subscription_code")
    subscription.updated_at = now_utc()
    subscription.last_event = "transaction.verify"

    # The authoritative recurring lifecycle will be maintained by webhooks.
    current_user.subscription_status = "active"
    db.commit()

    return {
        "status": "success",
        "plan": subscription.plan,
        "subscription_status": current_user.subscription_status,
        "reference": reference,
    }


@router.get("/manage")
async def manage_subscription(
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subscription = current_user.subscription
    if not subscription or not subscription.paystack_subscription_code:
        raise HTTPException(status_code=404, detail="No Paystack subscription found")

    try:
        result = await get_subscription_manage_link(subscription.paystack_subscription_code)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"link": result.get("data", {}).get("link")}


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")
    if not verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    event = payload.get("event", "")
    data = payload.get("data") or {}
    apply_subscription_event(db, event, data)
    return {"received": True}
