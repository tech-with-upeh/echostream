import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBPaymentHistory, DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    fetch_customer_subscriptions_by_code,
    fetch_subscription,
    get_plan_code,
    verify_transaction,
)

router = APIRouter(prefix="/payments", tags=["Payments"])
PAID_PLANS = {"essential", "pro"}
VALID_INTERVALS = {"month", "year"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _metadata(subscription: DBSubscription | None, transaction: dict) -> dict:
    value = transaction.get("metadata")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
            if isinstance(value, dict):
                return value
        except (TypeError, json.JSONDecodeError):
            pass
    if subscription and subscription.metadata_json:
        try:
            value = json.loads(subscription.metadata_json)
            if isinstance(value, dict):
                return value
        except (TypeError, json.JSONDecodeError):
            pass
    return {}


def _interval_from_plan(plan_obj: dict) -> str | None:
    return {"monthly": "month", "annually": "year"}.get(plan_obj.get("interval"))


def _transaction_plan_interval(data: dict, subscription: DBSubscription | None) -> tuple[str | None, str | None]:
    metadata = _metadata(subscription, data)
    plan = metadata.get("pending_plan") or metadata.get("plan")
    interval = metadata.get("pending_interval") or metadata.get("interval")
    plan_obj = data.get("plan") or {}
    if isinstance(plan_obj, dict):
        mapped_interval = _interval_from_plan(plan_obj)
        if mapped_interval:
            interval = interval if interval in VALID_INTERVALS else mapped_interval
        plan_code = plan_obj.get("plan_code")
        if plan_code and not plan:
            for candidate in PAID_PLANS:
                for candidate_interval in VALID_INTERVALS:
                    try:
                        if get_plan_code(candidate, candidate_interval) == plan_code:
                            return candidate, candidate_interval
                    except PaystackError:
                        pass
    return (str(plan).lower() if plan else None, interval if interval in VALID_INTERVALS else None)


async def _find_local_subscription(db: AsyncSession, reference: str, user_id: int | None = None) -> DBSubscription | None:
    query = select(DBSubscription).where(DBSubscription.reference == reference)
    if user_id is not None:
        query = query.where(DBSubscription.user_id == user_id)
    result = await db.execute(query)
    subscription = result.scalar_one_or_none()
    if subscription:
        return subscription
    if user_id is not None:
        result = await db.execute(
            select(DBSubscription).where(
                DBSubscription.user_id == user_id,
                DBSubscription.metadata_json.like(f'%"pending_change_reference": "{reference}"%'),
            )
        )
        return result.scalar_one_or_none()
    return None


async def _find_paystack_subscription(customer_code: str | None, authorization_code: str | None, plan: str | None, interval: str | None) -> tuple[dict | None, str | None]:
    if not customer_code:
        return None, None
    try:
        result = await fetch_customer_subscriptions_by_code(customer_code)
    except PaystackError:
        return None, None

    subscriptions = result.get("data") or []
    candidates = []
    target_plan_code = None
    if plan in PAID_PLANS and interval in VALID_INTERVALS:
        try:
            target_plan_code = get_plan_code(plan, interval)
        except PaystackError:
            pass

    for item in subscriptions:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).lower() not in {"active", "non-renewing"}:
            continue
        auth = item.get("authorization") or {}
        item_auth = auth.get("authorization_code") if isinstance(auth, dict) else None
        item_plan = item.get("plan") or {}
        item_plan_code = item_plan.get("plan_code") if isinstance(item_plan, dict) else None
        score = 0
        if authorization_code and item_auth == authorization_code:
            score += 100
        if target_plan_code and item_plan_code == target_plan_code:
            score += 50
        if score:
            candidates.append((score, item))

    if not candidates:
        return None, None
    candidates.sort(key=lambda value: value[0], reverse=True)
    selected = candidates[0][1]
    return selected, selected.get("subscription_code")


async def _sync_transaction(db: AsyncSession, data: dict, local_subscription: DBSubscription | None, user: DBUser) -> tuple[bool, str | None]:
    metadata = _metadata(local_subscription, data)
    plan, interval = _transaction_plan_interval(data, local_subscription)
    customer = data.get("customer") or {}
    authorization = data.get("authorization") or {}
    customer_code = customer.get("customer_code") if isinstance(customer, dict) else None
    authorization_code = authorization.get("authorization_code") if isinstance(authorization, dict) else None

    paystack_subscription, subscription_code = await _find_paystack_subscription(
        customer_code,
        authorization_code,
        plan,
        interval,
    )

    recurring = bool(paystack_subscription and subscription_code)
    if not plan and local_subscription:
        plan = local_subscription.plan
    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Payment metadata does not identify a paid plan")

    if interval not in VALID_INTERVALS:
        interval = _interval_from_plan((paystack_subscription or {}).get("plan") or {})

    if not interval:
        interval = metadata.get("interval") if metadata.get("interval") in VALID_INTERVALS else None

    channel = str(data.get("channel") or "").lower() or None
    status_value = str(data.get("status") or "unknown").lower()
    paid_at = _parse_dt(data.get("paid_at")) or _parse_dt(data.get("created_at")) or _now()

    if local_subscription:
        local_subscription.plan = plan
        if customer_code:
            local_subscription.paystack_customer_code = customer_code
        if authorization_code:
            local_subscription.authorization_code = authorization_code
        if subscription_code:
            local_subscription.paystack_subscription_code = subscription_code
        if paystack_subscription:
            sub_status = str(paystack_subscription.get("status") or "active").lower()
            local_subscription.status = sub_status
            start = _parse_dt(paystack_subscription.get("start"))
            end = _parse_dt(paystack_subscription.get("next_payment_date"))
            if start:
                local_subscription.current_period_start = start
            if end:
                local_subscription.current_period_end = end
                user.subscription_ends_at = end
        elif status_value == "success":
            local_subscription.status = "active"
            local_subscription.current_period_start = paid_at
        local_subscription.cancel_at_period_end = not recurring
        local_subscription.last_event = "transaction.verify.recurring" if recurring else "transaction.verify.one_time"
        local_subscription.updated_at = _now()
        local_metadata = _metadata(local_subscription, {})
        local_metadata.update({"plan": plan, "recurring": recurring, "payment_channel": channel or "unknown"})
        if interval:
            local_metadata["interval"] = interval
        local_metadata["last_payment_reference"] = data.get("reference")
        local_subscription.metadata_json = json.dumps(local_metadata)

        if recurring and subscription_code:
            try:
                detail = (await fetch_subscription(subscription_code)).get("data") or {}
                end = _parse_dt(detail.get("next_payment_date"))
                if end:
                    local_subscription.current_period_end = end
                    user.subscription_ends_at = end
            except PaystackError:
                pass

    if status_value == "success":
        user.plan = plan
        user.subscription_status = "active"
        if local_subscription and local_subscription.current_period_end:
            user.subscription_ends_at = local_subscription.current_period_end

    reference = data.get("reference")
    if reference:
        payment_values = {
            "user_id": user.id,
            "subscription_id": local_subscription.id if local_subscription else None,
            "payment_id": f"ES-PAY-{uuid.uuid4().hex}",
            "receipt_number": f"ES-RCP-{uuid.uuid4().hex}",
            "provider": "paystack",
            "provider_reference": reference,
            "reference": reference,
            "plan": plan,
            "interval": interval,
            "amount": int(data.get("amount") or 0) // 100,
            "currency": str(data.get("currency") or "NGN").upper(),
            "status": status_value,
            "channel": channel,
            "method": channel,
            "payment_method": "recurring" if recurring else "one_time",
            "billing_type": "recurring" if recurring else "one_time",
            "event": "transaction.verify.recurring" if recurring else "transaction.verify.one_time",
            "paid_at": paid_at,
            "created_at": _now(),
        }
        stmt = insert(DBPaymentHistory).values(**payment_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DBPaymentHistory.reference],
            set_={
                "subscription_id": stmt.excluded.subscription_id,
                "provider": stmt.excluded.provider,
                "provider_reference": stmt.excluded.provider_reference,
                "plan": stmt.excluded.plan,
                "interval": stmt.excluded.interval,
                "amount": stmt.excluded.amount,
                "currency": stmt.excluded.currency,
                "status": stmt.excluded.status,
                "channel": stmt.excluded.channel,
                "method": stmt.excluded.method,
                "payment_method": stmt.excluded.payment_method,
                "billing_type": stmt.excluded.billing_type,
                "event": stmt.excluded.event,
                "paid_at": stmt.excluded.paid_at,
            },
        )
        await db.execute(stmt)

    await db.commit()
    return recurring, subscription_code


async def _verify_and_sync(db: AsyncSession, reference: str, user: DBUser) -> tuple[dict, bool, str | None]:
    local_subscription = await _find_local_subscription(db, reference, user.id)
    if not local_subscription:
        raise HTTPException(status_code=404, detail="Payment reference not found")
    try:
        result = await verify_transaction(reference)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    data = result.get("data") or {}
    customer = data.get("customer") or {}
    metadata = _metadata(local_subscription, data)
    if metadata.get("user_id") is not None and str(metadata.get("user_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="Payment does not belong to this user")
    if customer.get("email") and str(customer["email"]).lower() != str(user.email).lower():
        raise HTTPException(status_code=403, detail="Payment does not belong to this user")
    recurring, subscription_code = await _sync_transaction(db, data, local_subscription, user)
    return data, recurring, subscription_code


@router.get("/callback", include_in_schema=False)
async def payment_callback(reference: str | None = None, trxref: str | None = None, db: AsyncSession = Depends(get_db)):
    payment_reference = reference or trxref
    if not payment_reference:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/payment/failed")

    local_subscription = await _find_local_subscription(db, payment_reference)
    if not local_subscription:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/payment/failed?reference={payment_reference}")
    user_result = await db.execute(select(DBUser).where(DBUser.id == local_subscription.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/payment/failed?reference={payment_reference}")

    try:
        data, recurring, _ = await _verify_and_sync(db, payment_reference, user)
    except HTTPException:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/payment/failed?reference={payment_reference}")

    target = "/payment/success" if str(data.get("status")).lower() == "success" else "/payment/failed"
    return RedirectResponse(url=f"{settings.FRONTEND_URL}{target}?reference={payment_reference}")


@router.get("/verify/{reference}")
async def verify_payment(reference: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    data, recurring, subscription_code = await _verify_and_sync(db, reference, current_user)
    return {
        "status": str(data.get("status") or "unknown").lower(),
        "payment_method": "recurring" if recurring else "one_time",
        "billing_type": "recurring" if recurring else "one_time",
        "payment_channel": str(data.get("channel") or "unknown").lower(),
        "subscription_code": subscription_code,
        "reference": reference,
    }
