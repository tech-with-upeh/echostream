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
    fetch_customer_subscriptions_by_code,
    fetch_subscription,
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


def parse_paystack_datetime(value) -> datetime | None:
    """Parse a Paystack ISO-8601 date into a timezone-aware datetime."""
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def update_subscription_period(
    user: DBUser,
    subscription: DBSubscription,
    data: dict,
) -> None:
    """Persist Paystack's current billing period on both records.

    Paystack exposes the next billing date as `next_payment_date` on
    subscription responses. We use that as the local subscription end date
    for the current paid period.
    """
    if not data:
        return

    start = parse_paystack_datetime(
        data.get("start")
        or data.get("current_period_start")
    )

    end = parse_paystack_datetime(
        data.get("next_payment_date")
        or data.get("current_period_end")
    )

    if start:
        subscription.current_period_start = start

    if end:
        subscription.current_period_end = end
        user.subscription_ends_at = end


def apply_subscription_event(
    db: Session,
    event: str,
    data: dict,
) -> None:
    subscription_code = data.get("subscription_code")

    customer = data.get("customer") or {}

    customer_code = (
        customer.get("customer_code")
        if isinstance(customer, dict)
        else None
    )

    metadata = data.get("metadata") or {}

    user_id = (
        metadata.get("user_id")
        if isinstance(metadata, dict)
        else None
    )

    subscription = None

    if subscription_code:
        subscription = (
            db.query(DBSubscription)
            .filter(
                DBSubscription.paystack_subscription_code
                == subscription_code
            )
            .first()
        )

    if not subscription and user_id:
        try:
            subscription = (
                db.query(DBSubscription)
                .filter(
                    DBSubscription.user_id == int(user_id)
                )
                .first()
            )
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

    # Paystack subscription payloads contain the billing period data.
    update_subscription_period(
        subscription.user,
        subscription,
        data,
    )

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
        # A cancelled/non-renewing subscription remains usable until the
        # current paid period ends.
        if (
            subscription.current_period_end
            and subscription.current_period_end > now_utc()
        ):
            user.subscription_status = "active"
        else:
            user.plan = "starter"
            user.subscription_status = "active"
            user.subscription_ends_at = None
            subscription.current_period_end = None

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
            detail=(
                "Starter is the free plan and does not require payment."
            ),
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
            detail=(
                f"You are already subscribed to the {plan} plan."
            ),
        )

    reference = (
        f"echostream_{current_user.id}_{uuid.uuid4().hex}"
    )

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

    data = result.get("data") or {}
    reference = data.get("reference")

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
        "authorization_url": data.get("authorization_url"),
        "access_code": data.get("access_code"),
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
    subscription = (
        db.query(DBSubscription)
        .filter(
            DBSubscription.reference == reference,
            DBSubscription.user_id == current_user.id,
        )
        .first()
    )

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

    data = result.get("data") or {}

    if data.get("status") != "success":
        return {
            "status": data.get("status", "failed"),
            "reference": reference,
        }

    subscription.status = "active"

    authorization = data.get("authorization") or {}
    customer = data.get("customer") or {}

    subscription.authorization_code = (
        authorization.get("authorization_code")
    )

    subscription.paystack_customer_code = (
        customer.get("customer_code")
    )

    subscription.paystack_subscription_code = (
        data.get("subscription_code")
    )

    subscription.updated_at = now_utc()
    subscription.last_event = "transaction.verify"

    current_user.plan = subscription.plan
    current_user.subscription_status = "active"

    # The transaction verification response can contain the subscription
    # code, but the authoritative billing-period dates are on the
    # subscription resource. Fetch it when available.
    subscription_data = None

    if subscription.paystack_subscription_code:
        try:
            subscription_result = await fetch_subscription(
                subscription.paystack_subscription_code
            )
            subscription_data = (
                subscription_result.get("data") or {}
            )
        except PaystackError:
            # Payment itself was verified successfully. Don't turn a
            # successful payment into a 502 just because the follow-up
            # subscription lookup failed. The webhook can fill the dates.
            subscription_data = None

    if subscription_data:
        update_subscription_period(
            current_user,
            subscription,
            subscription_data,
        )

        # Keep the email token available for subscription operations.
        subscription.paystack_email_token = (
            subscription_data.get("email_token")
        )

        subscription.cancel_at_period_end = (
            str(subscription_data.get("status", "")).lower()
            == "non-renewing"
        )

    db.commit()

    return {
        "status": "success",
        "plan": current_user.plan,
        "subscription_status": current_user.subscription_status,
        "subscription_ends_at": (
            current_user.subscription_ends_at
        ),
        "reference": reference,
    }


@router.get("/manage")
async def manage_subscription(
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subscription = current_user.subscription

    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="No subscription record found",
        )

    if current_user.plan not in PAID_PLANS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Starter is a free plan and has no subscription to manage"
            ),
        )

    subscription_code = subscription.paystack_subscription_code

    if (
        not subscription_code
        and subscription.paystack_customer_code
    ):
        try:
            result = await fetch_customer_subscriptions_by_code(
                subscription.paystack_customer_code
            )
        except PaystackError as exc:
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        paystack_subscriptions = result.get("data") or []

        matching = next(
            (
                item
                for item in paystack_subscriptions
                if str(item.get("status", "")).lower()
                in {"active", "non-renewing"}
                and str(
                    (item.get("plan") or {}).get("name", "")
                ).lower()
                == current_user.plan.lower()
            ),
            None,
        )

        if matching is None and paystack_subscriptions:
            matching = paystack_subscriptions[0]

        if matching:
            subscription_code = matching.get(
                "subscription_code"
            )

            subscription.paystack_subscription_code = (
                subscription_code
            )

            subscription.status = str(
                matching.get(
                    "status",
                    subscription.status,
                )
            ).lower()

            customer = matching.get("customer") or {}

            if customer.get("customer_code"):
                subscription.paystack_customer_code = (
                    customer.get("customer_code")
                )

            update_subscription_period(
                current_user,
                subscription,
                matching,
            )

            subscription.updated_at = now_utc()
            db.commit()

    if not subscription_code:
        raise HTTPException(
            status_code=404,
            detail="No active Paystack subscription found",
        )

    # Refresh the subscription from Paystack so subscription_ends_at stays
    # accurate even if a webhook was delayed or missed.
    try:
        subscription_result = await fetch_subscription(
            subscription_code
        )
        subscription_data = (
            subscription_result.get("data") or {}
        )
    except PaystackError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    update_subscription_period(
        current_user,
        subscription,
        subscription_data,
    )

    subscription.status = str(
        subscription_data.get(
            "status",
            subscription.status,
        )
    ).lower()

    subscription.paystack_email_token = (
        subscription_data.get("email_token")
    )

    subscription.cancel_at_period_end = (
        subscription.status == "non-renewing"
    )

    subscription.updated_at = now_utc()

    db.commit()

    try:
        result = await get_subscription_manage_link(
            subscription_code
        )
    except PaystackError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    link = (result.get("data") or {}).get("link")

    if not link:
        raise HTTPException(
            status_code=502,
            detail=(
                "Paystack did not return "
                "a subscription management link"
            ),
        )

    return {
        "link": link,
        "plan": current_user.plan,
        "subscription_status": current_user.subscription_status,
        "subscription_ends_at": current_user.subscription_ends_at,
        "subscription_code": subscription_code,
    }


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
)
async def paystack_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    signature = request.headers.get(
        "x-paystack-signature",
        "",
    )

    if not verify_webhook_signature(
        raw_body,
        signature,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )

    try:
        payload = json.loads(
            raw_body.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
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
