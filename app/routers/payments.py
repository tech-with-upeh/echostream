import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    fetch_customer_subscriptions,
    get_plan_code,
    get_subscription_manage_link,
    initialize_transaction,
    verify_transaction,
    verify_webhook_signature,
)

router = APIRouter(prefix="/payments", tags=["Payments"])
PAID_PLANS = {"essential", "pro"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def apply_subscription_event(db: Session, event: str, data: dict) -> None:
    subscription_code = data.get("subscription_code")
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
        try:
            subscription = db.query(DBSubscription).filter(
                DBSubscription.user_id == int(user_id)
            ).first()
        except (TypeError, ValueError):
            subscription = None

    if not subscription:
        return

    subscription.last_event = event
    subscription.updated_at = now_utc()

    if customer_code:
        subscription.paystack_customer_code = customer_code

    if subscription_code:
        subscription.paystack_subscription_code = subscription_code

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
        user.plan = subscription.plan
        user.subscription_status = "active"

    elif new_status in {"canceled", "non_renewing"}:
        if (
            subscription.current_period_end
            and subscription.current_period_end > now_utc()
        ):
            user.subscription_status = "active"
        else:
            user.plan = "starter"
            user.subscription_status = "active"
            user.subscription_ends_at = None

    db.commit()


@router.post("/subscribe")
async def create_subscription_checkout(
    plan: str,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = plan.lower().strip()

    if plan == "starter":
        raise HTTPException(
            status_code=400,
            detail="Starter is the free plan and does not require payment.",
        )

    if plan not in PAID_PLANS:
        raise HTTPException(
            status_code=400,
            detail="Invalid paid subscription plan",
        )

    if (
        current_user.plan == plan
        and current_user.subscription_status == "active"
    ):
        raise HTTPException(
            status_code=400,
            detail=f"You are already subscribed to the {plan} plan.",
        )

    reference = f"echostream_{current_user.id}_{uuid.uuid4().hex}"

    try:
        result = await initialize_transaction(
            email=current_user.email,
            plan_code=get_plan_code(plan),
            reference=reference,
            callback_url=settings.PAYSTACK_CALLBACK_URL,
            metadata={
                "user_id": current_user.id,
                "plan": plan,
            },
        )
    except PaystackError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    reference = result["data"].get("reference")

    if not reference:
        raise HTTPException(
            status_code=502,
            detail="Paystack did not return a payment reference",
        )

    timestamp = now_utc()
    subscription = current_user.subscription

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


@router.get("/callback")
async def payment_callback(
    reference: str | None = None,
    trxref: str | None = None,
):
    payment_reference = reference or trxref

    if not payment_reference:
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/payment/failed"
        )

    return RedirectResponse(
        url=(
            f"{settings.FRONTEND_URL}/payment/success"
            f"?reference={payment_reference}"
        )
    )


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
        raise HTTPException(
            status_code=404,
            detail="Payment reference not found",
        )

    try:
        result = await verify_transaction(reference)
    except PaystackError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    data = result.get("data", {})

    if data.get("status") != "success":
        return {
            "status": data.get("status", "failed"),
            "reference": reference,
        }

    subscription.status = "active"
    subscription.authorization_code = (
        data.get("authorization") or {}
    ).get("authorization_code")
    subscription.paystack_customer_code = (
        data.get("customer") or {}
    ).get("customer_code")
    subscription.paystack_subscription_code = data.get(
        "subscription_code"
    )
    subscription.updated_at = now_utc()
    subscription.last_event = "transaction.verify"

    current_user.plan = subscription.plan
    current_user.subscription_status = "active"
    db.commit()

    return {
        "status": "success",
        "plan": current_user.plan,
        "subscription_status": current_user.subscription_status,
        "reference": reference,
    }


@router.get("/manage")
async def manage_subscription(
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return Paystack's hosted subscription-management link.

    For paid users, recover a missing local Paystack subscription code from
    the customer's Paystack subscriptions before returning 404. This makes
    the endpoint resilient when a webhook was missed or an older payment was
    verified before the subscription code was persisted locally.
    """
    subscription = current_user.subscription

    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="No subscription record found",
        )

    if current_user.plan not in PAID_PLANS:
        raise HTTPException(
            status_code=400,
            detail="Starter is a free plan and has no subscription to manage",
        )

    subscription_code = subscription.paystack_subscription_code

    # Recover the Paystack subscription code if it is missing locally.
    if not subscription_code and subscription.paystack_customer_code:
        try:
            result = await fetch_customer_subscriptions(
                subscription.paystack_customer_code
            )
        except PaystackError as exc:
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        paystack_subscriptions = result.get("data") or []

        # Prefer the subscription matching this user's current plan.
        matching = next(
            (
                item
                for item in paystack_subscriptions
                if str(item.get("status", "")).lower()
                in {"active", "non-renewing"}
                and str(item.get("plan", {}).get("name", "")).lower()
                == current_user.plan.lower()
            ),
            None,
        )

        if matching is None and paystack_subscriptions:
            matching = paystack_subscriptions[0]

        if matching:
            subscription_code = matching.get("subscription_code")
            subscription.paystack_subscription_code = subscription_code
            subscription.status = str(
                matching.get("status") or subscription.status
            ).lower()
            subscription.updated_at = now_utc()
            db.commit()

    if not subscription_code:
        raise HTTPException(
            status_code=404,
            detail="No active Paystack subscription found",
        )

    try:
        result = await get_subscription_manage_link(subscription_code)
    except PaystackError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    link = (result.get("data") or {}).get("link")

    if not link:
        raise HTTPException(
            status_code=502,
            detail="Paystack did not return a subscription management link",
        )

    return {
        "link": link,
        "plan": current_user.plan,
        "subscription_status": current_user.subscription_status,
        "subscription_code": subscription_code,
    }


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    signature = request.headers.get(
        "x-paystack-signature",
        "",
    )

    if not verify_webhook_signature(raw_body, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )

    try:
        payload = json.loads(
            raw_body.decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook payload",
        ) from exc

    apply_subscription_event(
        db,
        payload.get("event", ""),
        payload.get("data") or {},
    )

    return {"received": True}
