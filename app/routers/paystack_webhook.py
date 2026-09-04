import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models import DBSubscription, DBUser
from app.paystack_service import verify_webhook_signature
from app.routers.payments import apply_subscription_event, get_metadata, parse_paystack_datetime

router = APIRouter(prefix="/payments", tags=["Payments"])


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def update_payment_details(subscription: DBSubscription, data: dict) -> None:
    """Persist the latest Paystack authorization without exposing secrets."""
    authorization = data.get("authorization") or {}
    if not isinstance(authorization, dict):
        return

    authorization_code = authorization.get("authorization_code")
    if authorization_code:
        subscription.authorization_code = authorization_code

    method = str(data.get("channel") or authorization.get("channel") or "").strip().lower()
    if method:
        subscription.payment_method = method

    brand = str(authorization.get("brand") or "").strip()
    if brand:
        subscription.payment_method_brand = brand

    last4 = str(authorization.get("last4") or "").strip()
    if last4:
        subscription.payment_method_last4 = last4

    bank = str(authorization.get("bank") or "").strip()
    if bank:
        subscription.payment_method_bank = bank

    card_type = str(authorization.get("card_type") or "").strip()
    if card_type:
        subscription.payment_method_card_type = card_type


async def find_subscription(db: AsyncSession, subscription_code: str | None) -> DBSubscription | None:
    if not subscription_code:
        return None
    result = await db.execute(
        select(DBSubscription)
        .where(DBSubscription.paystack_subscription_code == subscription_code)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def handle_subscription_not_renew(
    db: AsyncSession,
    data: dict,
) -> None:
    subscription = await find_subscription(db, data.get("subscription_code"))
    if not subscription:
        return

    user_result = await db.execute(
        select(DBUser).where(DBUser.id == subscription.user_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        return

    next_payment_date = parse_paystack_datetime(data.get("next_payment_date"))
    if next_payment_date:
        subscription.current_period_end = next_payment_date
        user.subscription_ends_at = next_payment_date

    # Paystack includes the current authorization on subscription.not_renew.
    # This is important for the update-payment-method flow: the preceding
    # refund.pending event belongs to the temporary update-card charge and does
    # not contain the new authorization. Persist the authorization from the
    # subscription event instead.
    update_payment_details(subscription, data)

    subscription.status = "non_renewing"
    subscription.cancel_at_period_end = True
    subscription.last_event = "subscription.not_renew"
    subscription.updated_at = now_utc()

    # The user remains on the paid plan until the current billing period ends.
    user.plan = subscription.plan
    user.subscription_status = "active"


async def handle_subscription_disable(
    db: AsyncSession,
    data: dict,
) -> None:
    subscription = await find_subscription(db, data.get("subscription_code"))
    if not subscription:
        return

    user_result = await db.execute(
        select(DBUser).where(DBUser.id == subscription.user_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        return

    # Keep any authorization/payment details Paystack supplied with the event.
    # The subscription is no longer active, but those fields are useful for
    # historical display and should not be confused with the active recurring
    # subscription identifiers below.
    update_payment_details(subscription, data)

    subscription.status = "canceled"
    subscription.cancel_at_period_end = False
    subscription.last_event = "subscription.disable"
    subscription.updated_at = now_utc()

    user.plan = "starter"
    user.subscription_status = "active"
    user.subscription_ends_at = None

    # The old Paystack subscription is no longer the active recurring source.
    subscription.paystack_subscription_code = None
    subscription.authorization_code = None


async def apply_webhook_event(db: AsyncSession, event: str, data: dict) -> None:
    event = (event or "").strip().lower()

    if event == "subscription.not_renew":
        await handle_subscription_not_renew(db, data)
        await db.commit()
        return

    if event == "subscription.disable":
        await handle_subscription_disable(db, data)
        await db.commit()
        return

    if event.startswith("refund."):
        # Refund events are payment/refund lifecycle events, not subscription
        # lifecycle events. In particular, refund.pending is emitted by
        # Paystack during the update-payment-method flow. It must never cancel,
        # downgrade, or otherwise mutate the user's active subscription.
        return

    await apply_subscription_event(db, event, data)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(request: Request, db: AsyncSession = Depends(get_db)):
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

    try:
        await apply_webhook_event(db, event, data)
    except Exception:
        await db.rollback()
        raise

    return {"received": True}
