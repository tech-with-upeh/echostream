import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBPaymentHistory, DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    disable_subscription,
    fetch_customer_subscriptions_by_code,
    fetch_subscription,
    get_plan_code,
    verify_transaction,
    verify_webhook_signature,
)

router = APIRouter(prefix="/payments", tags=["Payments"])
PAID_PLANS = {"essential", "pro"}
VALID_INTERVALS = {"month", "year"}
RECURRING_CHANNELS = {"card", "direct_debit"}


def _update_payment_details(subscription: DBSubscription, data: dict) -> None:
    """Persist the latest Paystack authorization without exposing secrets."""
    authorization = data.get("authorization") or {}
    if not isinstance(authorization, dict):
        return
    if authorization.get("authorization_code"):
        subscription.authorization_code = authorization["authorization_code"]
    method = str(data.get("channel") or authorization.get("channel") or "").strip().lower()
    if method:
        subscription.payment_method = method
    for field, key in (("payment_method_brand", "brand"), ("payment_method_last4", "last4"), ("payment_method_bank", "bank"), ("payment_method_card_type", "card_type")):
        value = str(authorization.get(key) or "").strip()
        if value:
            setattr(subscription, field, value)


async def _find_subscription_by_code(db: AsyncSession, subscription_code: str | None) -> DBSubscription | None:
    if not subscription_code:
        return None
    result = await db.execute(select(DBSubscription).where(DBSubscription.paystack_subscription_code == subscription_code).with_for_update())
    return result.scalar_one_or_none()


def _extract_subscription_code_from_refund(data: dict) -> str | None:
    """Paystack's hosted update-card flow does a small verify-charge + refund;
    the refund note carries the subscription code so we can refresh the card."""
    for key in ("customer_note", "merchant_note"):
        note = data.get(key)
        if not isinstance(note, str):
            continue
        marker = "[Subscription:"
        start = note.find(marker)
        if start == -1:
            continue
        start += len(marker)
        end = note.find("]", start)
        if end != -1 and note[start:end].strip():
            return note[start:end].strip()
    return None


async def _refresh_card_from_refund(db: AsyncSession, subscription_code: str | None) -> None:
    subscription = await _find_subscription_by_code(db, subscription_code)
    if not subscription:
        # Cached code may have drifted — fetch the subscription from Paystack
        # and fall back to matching on its customer_code before giving up.
        try:
            remote = (await fetch_subscription(subscription_code)).get("data") or {}
        except PaystackError:
            return
        customer_code = (remote.get("customer") or {}).get("customer_code")
        if not customer_code:
            return
        result = await db.execute(select(DBSubscription).where(DBSubscription.paystack_customer_code == customer_code).with_for_update())
        subscription = result.scalars().first()
        if not subscription:
            return
        if subscription.paystack_subscription_code != subscription_code:
            subscription.paystack_subscription_code = subscription_code
    else:
        try:
            remote = (await fetch_subscription(subscription_code)).get("data") or {}
        except PaystackError:
            return  # a later webhook or reconciliation pass can retry

    _update_payment_details(subscription, remote)
    subscription.updated_at = _now()
    await db.commit()


async def _find_subscription_for_lifecycle_event(db: AsyncSession, data: dict) -> DBSubscription | None:
    """Resolve the local subscription this lifecycle event belongs to, and make
    sure our cached subscription_code matches what Paystack actually has —
    a strict equality lookup would silently drop the event if the two ever drift."""
    subscription_code = data.get("subscription_code")
    subscription = await _find_subscription_by_code(db, subscription_code)

    if not subscription:
        customer = data.get("customer") or {}
        customer_email = customer.get("email") if isinstance(customer, dict) else None
        if customer_email:
            result = await db.execute(select(DBUser).where(DBUser.email == customer_email).with_for_update())
            userID = result.scalars().first()
            SubRes = await db.execute(select(DBSubscription).where(DBSubscription.user_id == userID.id))
            subscription = SubRes.scalars().first()

    if subscription and subscription_code and subscription.paystack_subscription_code != subscription_code:
        subscription.paystack_subscription_code = subscription_code

    return subscription


async def _handle_subscription_not_renew(db: AsyncSession, data: dict) -> None:
    subscription = await _find_subscription_for_lifecycle_event(db, data)
    if not subscription:
        return
    user_result = await db.execute(select(DBUser).where(DBUser.id == subscription.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return

    next_payment_date = _parse_dt(data.get("next_payment_date"))
    if next_payment_date:
        # Paystack can redeliver this webhook; don't let a stale retry roll
        # the period end backwards past what a newer event already set.
        current_end = subscription.current_period_end
        if not current_end or next_payment_date >= (current_end if current_end.tzinfo else current_end.replace(tzinfo=timezone.utc)):
            subscription.current_period_end = next_payment_date
            user.subscription_ends_at = next_payment_date

    customer = data.get("customer") or {}
    if isinstance(customer, dict) and customer.get("customer_code"):
        subscription.paystack_customer_code = customer["customer_code"]

    _update_payment_details(subscription, data)  # this event can follow an update-card operation
    subscription.status = "non_renewing"
    subscription.cancel_at_period_end = True
    subscription.last_event = "subscription.not_renew"
    subscription.updated_at = _now()
    user.plan = subscription.plan
    user.subscription_status = "active"  # stays on the paid plan until the period ends
    await db.commit()


async def _handle_subscription_disable(db: AsyncSession, data: dict) -> None:
    subscription = await _find_subscription_for_lifecycle_event(db, data)
    if not subscription:
        return
    user_result = await db.execute(select(DBUser).where(DBUser.id == subscription.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return
    _update_payment_details(subscription, data)
    subscription.status = "canceled"
    subscription.cancel_at_period_end = False
    subscription.last_event = "subscription.disable"
    subscription.updated_at = _now()
    user.plan = "starter"
    user.subscription_status = "active"
    user.subscription_ends_at = None
    # The Paystack subscription is gone; stop treating this row as recurring
    # (this is what upgrade.py's `recurring` check relies on).
    subscription.paystack_subscription_code = None
    subscription.authorization_code = None
    await db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
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
        if mapped_interval and interval not in VALID_INTERVALS:
            interval = mapped_interval
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
        result = await db.execute(select(DBSubscription).where(DBSubscription.user_id == user_id, DBSubscription.metadata_json.like(f'%\"pending_change_reference\": \"{reference}\"%')))
        return result.scalar_one_or_none()
    return None


async def _find_paystack_subscription(customer_code: str | None, authorization_code: str | None, plan: str | None, interval: str | None) -> tuple[dict | None, str | None]:
    if not customer_code:
        return None, None
    for attempt in range(2):
        try:
            result = await fetch_customer_subscriptions_by_code(customer_code)
        except PaystackError:
            result = None
        if result is not None:
            subscriptions = result.get("data") or []
            candidates = []
            target_plan_code = None
            if plan in PAID_PLANS and interval in VALID_INTERVALS:
                try:
                    target_plan_code = get_plan_code(plan, interval)
                except PaystackError:
                    pass
            for item in subscriptions:
                if not isinstance(item, dict) or str(item.get("status", "")).lower() not in {"active", "non-renewing"}:
                    continue
                auth = item.get("authorization") or {}
                item_auth = auth.get("authorization_code") if isinstance(auth, dict) else None
                item_plan = item.get("plan") or {}
                item_plan_code = item_plan.get("plan_code") if isinstance(item_plan, dict) else None
                score = (100 if authorization_code and item_auth == authorization_code else 0) + (50 if target_plan_code and item_plan_code == target_plan_code else 0)
                if score:
                    candidates.append((score, item))
            if candidates:
                candidates.sort(key=lambda value: value[0], reverse=True)
                selected = candidates[0][1]
                return selected, selected.get("subscription_code")
        if attempt == 0:
            await asyncio.sleep(0.5)
    return None, None


async def _disable_previous_paystack_subscription(subscription_code: str | None) -> None:
    if not subscription_code:
        return
    try:
        detail = (await fetch_subscription(subscription_code)).get("data") or {}
        if str(detail.get("status") or "").lower() in {"active", "non-renewing"}:
            email_token = detail.get("email_token")
            if email_token:
                await disable_subscription(subscription_code, email_token)
    except PaystackError:
        pass


def _payment_method_details(data: dict) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    authorization = data.get("authorization") or {}
    if not isinstance(authorization, dict):
        authorization = {}
    method = str(data.get("channel") or authorization.get("channel") or "").lower().strip() or None
    brand = str(authorization.get("brand") or authorization.get("card_type") or "").strip() or None
    last4 = str(authorization.get("last4") or "").strip() or None
    bank = str(authorization.get("bank") or "").strip() or None
    card_type = str(authorization.get("card_type") or "").strip() or None
    return method, brand, last4, bank, card_type


async def _sync_transaction(db: AsyncSession, data: dict, local_subscription: DBSubscription | None, user: DBUser) -> tuple[bool, str | None]:
    metadata = _metadata(local_subscription, data)
    plan, interval = _transaction_plan_interval(data, local_subscription)
    customer = data.get("customer") or {}
    authorization = data.get("authorization") or {}
    customer_code = customer.get("customer_code") if isinstance(customer, dict) else None
    authorization_code = authorization.get("authorization_code") if isinstance(authorization, dict) else None
    channel, method_brand, method_last4, method_bank, method_card_type = _payment_method_details(data)
    status_value = str(data.get("status") or "unknown").lower()
    paid_at = _parse_dt(data.get("paid_at")) or _parse_dt(data.get("created_at")) or _now()
    paystack_subscription, subscription_code = await _find_paystack_subscription(customer_code, authorization_code, plan, interval)
    recurring = channel in RECURRING_CHANNELS
    if paystack_subscription and subscription_code and channel in RECURRING_CHANNELS:
        recurring = True
    if not plan and local_subscription:
        plan = local_subscription.plan
    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Payment metadata does not identify a paid plan")
    if interval not in VALID_INTERVALS:
        interval = _interval_from_plan((paystack_subscription or {}).get("plan") or {})
    if not interval:
        interval = metadata.get("interval") if metadata.get("interval") in VALID_INTERVALS else None
    old_subscription_code = local_subscription.paystack_subscription_code if local_subscription else None
    if local_subscription:
        if status_value == "success" and not recurring and old_subscription_code:
            await _disable_previous_paystack_subscription(old_subscription_code)
        local_subscription.plan = plan
        local_subscription.reference = data.get("reference") or local_subscription.reference
        local_subscription.status = "active" if status_value == "success" else status_value
        local_subscription.cancel_at_period_end = False
        local_subscription.last_event = "transaction.verify.recurring" if recurring else "transaction.verify.one_time"
        local_subscription.updated_at = _now()
        if customer_code:
            local_subscription.paystack_customer_code = customer_code

        # Keep the subscription's payment fields as the latest successful
        # authorization snapshot. Failed charges must never overwrite the
        # currently active payment method.
        if status_value == "success":
            local_subscription.payment_method = channel
            local_subscription.payment_method_brand = method_brand
            local_subscription.payment_method_last4 = method_last4
            local_subscription.payment_method_bank = method_bank
            local_subscription.payment_method_card_type = method_card_type

        if recurring:
            local_subscription.paystack_subscription_code = subscription_code
            local_subscription.authorization_code = authorization_code
        else:
            local_subscription.paystack_subscription_code = None
            local_subscription.authorization_code = None
        if paystack_subscription and recurring:
            start = _parse_dt(paystack_subscription.get("start"))
            end = _parse_dt(paystack_subscription.get("next_payment_date"))
            if start:
                local_subscription.current_period_start = start
            if end:
                local_subscription.current_period_end = end
                user.subscription_ends_at = end
            try:
                detail = (await fetch_subscription(subscription_code)).get("data") or {}
                end = _parse_dt(detail.get("next_payment_date"))
                if end:
                    local_subscription.current_period_end = end
                    user.subscription_ends_at = end
            except PaystackError:
                pass
        elif status_value == "success":
            local_subscription.current_period_start = paid_at
            if interval in VALID_INTERVALS:
                from app.routers.payments import add_billing_period
                local_subscription.current_period_end = add_billing_period(paid_at, interval)
                user.subscription_ends_at = local_subscription.current_period_end
            else:
                local_subscription.current_period_end = None
                user.subscription_ends_at = None
        local_metadata = _metadata(local_subscription, {})
        local_metadata.update({"plan": plan, "recurring": recurring, "payment_channel": channel or "unknown"})
        if interval:
            local_metadata["interval"] = interval
        local_metadata["last_payment_reference"] = data.get("reference")
        for key in ("pending_plan", "pending_interval", "pending_subscription_code", "pending_change_reference"):
            local_metadata.pop(key, None)
        if not recurring:
            local_metadata.pop("old_subscription_code", None)
            local_metadata["recurring"] = False
        local_subscription.metadata_json = json.dumps(local_metadata)
    if status_value == "success":
        user.plan = plan
        user.subscription_status = "active"
        if local_subscription:
            user.subscription_ends_at = local_subscription.current_period_end
    reference = data.get("reference")
    if reference:
        values = {
            "user_id": user.id,
            "subscription_id": local_subscription.id if local_subscription else None,
            "payment_id": f"ES-PAY-{uuid.uuid4().hex}",
            "receipt_number": f"ES-RCP-{uuid.uuid4().hex}",
            "provider": "paystack",
            "provider_reference": reference,
            "reference": reference,
            "plan": plan,
            "interval": interval,
            "amount": int(data.get("amount") or 0) / 100,
            "currency": str(data.get("currency") or "NGN").upper(),
            "status": status_value,
            "billing_type": "recurring" if recurring else "one_time",
            "method": channel,
            "method_brand": method_brand,
            "method_last4": method_last4,
            "event": "transaction.verify.recurring" if recurring else "transaction.verify.one_time",
            "paid_at": paid_at,
            "created_at": _now(),
        }
        stmt = insert(DBPaymentHistory).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=[DBPaymentHistory.reference], set_={
            "subscription_id": stmt.excluded.subscription_id,
            "provider": stmt.excluded.provider,
            "provider_reference": stmt.excluded.provider_reference,
            "plan": stmt.excluded.plan,
            "interval": stmt.excluded.interval,
            "amount": stmt.excluded.amount,
            "currency": stmt.excluded.currency,
            "status": stmt.excluded.status,
            "billing_type": stmt.excluded.billing_type,
            "method": stmt.excluded.method,
            "method_brand": stmt.excluded.method_brand,
            "method_last4": stmt.excluded.method_last4,
            "event": stmt.excluded.event,
            "paid_at": stmt.excluded.paid_at,
        })
        await db.execute(stmt)
    await db.commit()
    return recurring, subscription_code if recurring else None


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
        data, _, _ = await _verify_and_sync(db, payment_reference, user)
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


@router.post("/webhook", status_code=200)
async def paystack_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")
    if not verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    event = str(payload.get("event") or "")
    data = payload.get("data") or {}

    # Charge events are transaction records. Reconcile them here so the
    # payment-history schema is the only representation used for history.
    # Non-charge subscription lifecycle events still use the existing
    # subscription-event handler in payments.py.
    if event in {"charge.success", "charge.failed"}:
        reference = data.get("reference")
        metadata = data.get("metadata") or {}
        user_id = metadata.get("user_id") if isinstance(metadata, dict) else None
        local_subscription = None
        if reference:
            local_subscription = await _find_local_subscription(db, reference, int(user_id) if user_id is not None else None)
        if not local_subscription and user_id is not None:
            try:
                local_subscription = await get_user_subscription_for_user(db, int(user_id))
            except (TypeError, ValueError):
                local_subscription = None
        if not local_subscription:
            raise HTTPException(status_code=404, detail="Payment reference not found")
        user_result = await db.execute(select(DBUser).where(DBUser.id == local_subscription.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        await _sync_transaction(db, data, local_subscription, user)
        return {"received": True}

    if event == "subscription.not_renew":
        await _handle_subscription_not_renew(db, data)
        return {"received": True}

    if event == "subscription.disable":
        await _handle_subscription_disable(db, data)
        return {"received": True}

    if event.startswith("refund."):
        subscription_code = _extract_subscription_code_from_refund(data)
        if subscription_code:
            await _refresh_card_from_refund(db, subscription_code)
        return {"received": True}

    # subscription.create and anything else still use the existing
    # subscription state machine in payments.py.
    from app.routers.payments import apply_subscription_event

    await apply_subscription_event(db, event, data)
    return {"received": True}


async def get_user_subscription_for_user(db: AsyncSession, user_id: int) -> DBSubscription | None:
    result = await db.execute(select(DBSubscription).where(DBSubscription.user_id == user_id))
    return result.scalar_one_or_none()
