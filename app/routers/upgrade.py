import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBSubscription, DBUser
from app.paystack_service import (
    PaystackError,
    create_subscription,
    disable_subscription,
    fetch_plan,
    fetch_subscription,
    get_plan_code,
    initialize_transaction,
    verify_transaction,
    verify_webhook_signature,
)

router = APIRouter(prefix="/payments", tags=["Payments"])
PAID_PLANS = {"essential", "pro"}
VALID_INTERVALS = {"month", "year"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
    start = parse_datetime(start) or now_utc()
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


def calculate_first_debit(now: datetime, target_interval: str, unused_credit_kobo: int, target_price_kobo: int) -> datetime:
    now = parse_datetime(now) or now_utc()
    target_price = Decimal(max(target_price_kobo, 1))
    unused = Decimal(max(unused_credit_kobo, 0))
    covered_periods = max(Decimal("1"), unused / target_price)
    first_period_end = add_billing_period(now, target_interval)
    period_seconds = Decimal(str((first_period_end - now).total_seconds()))
    return now + timedelta(seconds=float(period_seconds * covered_periods))


async def get_user_subscription(db: AsyncSession, user_id: int) -> DBSubscription | None:
    result = await db.execute(select(DBSubscription).where(DBSubscription.user_id == user_id))
    return result.scalar_one_or_none()


async def get_upgrade_context(db: AsyncSession, current_user: DBUser, plan: str, interval: str):
    plan = plan.strip().lower()
    interval = interval.strip().lower()
    if plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Invalid paid subscription plan")
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid billing interval. Use month or year.")
    subscription = await get_user_subscription(db, current_user.id)
    if not subscription:
        raise HTTPException(status_code=400, detail="No subscription record found")

    metadata = get_metadata(subscription)
    current_plan = str(current_user.plan or subscription.plan or "").strip().lower()
    current_interval = str(metadata.get("interval") or "").strip().lower()
    recurring = bool(metadata.get("recurring", bool(subscription.authorization_code)))
    if current_plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail="Only paid subscriptions can be upgraded")
    if current_interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Current subscription billing interval is unavailable")
    if not recurring or not subscription.authorization_code or not subscription.paystack_subscription_code:
        raise HTTPException(status_code=400, detail="An active recurring subscription is required for an upgrade")
    if current_plan == plan and current_interval == interval:
        raise HTTPException(status_code=400, detail="You are already on this plan and billing interval")

    try:
        current_plan_data = await fetch_plan(get_plan_code(current_plan, current_interval))
        target_plan_data = await fetch_plan(get_plan_code(plan, interval))
        current_remote = await fetch_subscription(subscription.paystack_subscription_code)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    current_price_kobo = int((current_plan_data.get("data") or {}).get("amount") or 0)
    target_price_kobo = int((target_plan_data.get("data") or {}).get("amount") or 0)
    if current_price_kobo <= 0 or target_price_kobo <= 0:
        raise HTTPException(status_code=502, detail="Could not determine subscription prices from Paystack")
    if target_price_kobo <= current_price_kobo:
        raise HTTPException(status_code=400, detail="The selected subscription is not an upgrade")

    remote_data = current_remote.get("data") or {}
    period_start = parse_datetime(remote_data.get("start")) or subscription.current_period_start
    period_end = parse_datetime(remote_data.get("next_payment_date")) or subscription.current_period_end
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="Could not determine the current billing period")
    period_start = period_start.astimezone(timezone.utc)
    period_end = period_end.astimezone(timezone.utc)
    now = now_utc()
    if period_end <= now:
        raise HTTPException(status_code=400, detail="The current subscription period has ended")

    total_seconds = Decimal(str((period_end - period_start).total_seconds()))
    remaining_seconds = max(Decimal(str((period_end - now).total_seconds())), Decimal("0"))
    if total_seconds <= 0:
        raise HTTPException(status_code=400, detail="Invalid current billing period")

    unused_value_kobo = int((Decimal(current_price_kobo) * remaining_seconds / total_seconds).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    upgrade_amount_kobo = max(target_price_kobo - unused_value_kobo, 0)
    first_debit = calculate_first_debit(now, interval, unused_value_kobo, target_price_kobo)

    return {
        "subscription": subscription,
        "metadata": metadata,
        "current_plan": current_plan,
        "current_interval": current_interval,
        "new_plan": plan,
        "new_interval": interval,
        "period_start": period_start,
        "period_end": period_end,
        "total_days": float(total_seconds / Decimal("86400")),
        "remaining_days": float(remaining_seconds / Decimal("86400")),
        "current_plan_price_kobo": current_price_kobo,
        "new_plan_price_kobo": target_price_kobo,
        "current_plan_price": float(Decimal(current_price_kobo) / Decimal("100")),
        "new_plan_price": float(Decimal(target_price_kobo) / Decimal("100")),
        "unused_value_kobo": unused_value_kobo,
        "unused_value": float(Decimal(unused_value_kobo) / Decimal("100")),
        "upgrade_amount_kobo": upgrade_amount_kobo,
        "upgrade_amount": float(Decimal(upgrade_amount_kobo) / Decimal("100")),
        "credit_remaining": 0,
        "first_debit": first_debit,
    }


async def disable_old_subscription(subscription_code: str, local_email_token: str | None = None) -> dict:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            remote = await fetch_subscription(subscription_code)
            data = remote.get("data") or {}
            status = str(data.get("status") or "").lower()
            if status in {"cancelled", "canceled", "completed"}:
                return data
            token = data.get("email_token") or local_email_token
            if not token:
                raise PaystackError("Paystack did not return an email token for the old subscription")
            await disable_subscription(subscription_code, token)
            verify = await fetch_subscription(subscription_code)
            verify_data = verify.get("data") or {}
            verify_status = str(verify_data.get("status") or "").lower()
            if verify_status in {"cancelled", "canceled", "completed", "non-renewing"}:
                return verify_data
            raise PaystackError(f"Old subscription remains in unexpected status: {verify_status or 'unknown'}")
        except PaystackError as exc:
            last_error = exc
    raise PaystackError(f"Could not disable old Paystack subscription {subscription_code}: {last_error}")


async def create_target_subscription(*, subscription: DBSubscription, plan: str, interval: str, authorization_code: str, first_debit: datetime) -> dict:
    if not subscription.paystack_customer_code:
        raise PaystackError("Paystack customer information is missing")
    result = await create_subscription(customer=subscription.paystack_customer_code, plan_code=get_plan_code(plan, interval), authorization_code=authorization_code, start_date=first_debit.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
    data = result.get("data") or {}
    if not data.get("subscription_code"):
        raise PaystackError("Paystack did not return the new subscription code")
    return data


async def complete_upgrade(db: AsyncSession, current_user: DBUser, subscription: DBSubscription, context: dict, *, payment_reference: str, authorization_code: str, payment_channel: str, paid_at: datetime | None = None, payment_amount_kobo: int | None = None) -> dict:
    metadata = get_metadata(subscription)
    old_code = metadata.get("previous_subscription_code") or subscription.paystack_subscription_code
    if not old_code:
        raise HTTPException(status_code=400, detail="Previous Paystack subscription code is missing")

    target_code = metadata.get("pending_upgrade_subscription_code")
    target_data = None
    if target_code:
        try:
            target_data = (await fetch_subscription(target_code)).get("data") or {}
        except PaystackError:
            target_data = None
    if not target_code:
        try:
            target_data = await create_target_subscription(subscription=subscription, plan=context["new_plan"], interval=context["new_interval"], authorization_code=authorization_code, first_debit=context["first_debit"])
            target_code = target_data.get("subscription_code")
            metadata["pending_upgrade_subscription_code"] = target_code
            metadata["upgrade_first_debit"] = context["first_debit"].isoformat()
            set_metadata(subscription, metadata)
            await db.commit()
        except PaystackError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        old_data = await disable_old_subscription(old_code, subscription.paystack_email_token)
    except PaystackError as exc:
        metadata["upgrade_cleanup_pending"] = True
        metadata["old_subscription_code"] = old_code
        metadata["pending_upgrade_subscription_code"] = target_code
        set_metadata(subscription, metadata)
        subscription.last_event = "subscription.upgrade.old_subscription_disable_pending"
        subscription.updated_at = now_utc()
        await db.commit()
        raise HTTPException(status_code=502, detail="Upgrade payment succeeded, but the old subscription could not be cancelled yet. No upgrade completion was recorded; retry verification to finish the transition.") from exc

    paid_at = paid_at or now_utc()
    target_data = target_data or {}
    period_start = parse_datetime(target_data.get("start")) or paid_at
    period_end = parse_datetime(target_data.get("next_payment_date")) or context["first_debit"]
    if period_end <= period_start:
        period_end = context["first_debit"]

    subscription.plan = context["new_plan"]
    subscription.status = "active"
    subscription.reference = payment_reference
    subscription.authorization_code = authorization_code
    subscription.paystack_subscription_code = target_code
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = False
    subscription.paystack_email_token = target_data.get("email_token") or subscription.paystack_email_token
    subscription.last_event = "subscription.upgrade.completed"
    subscription.updated_at = now_utc()

    metadata.update({"plan": context["new_plan"], "interval": context["new_interval"], "recurring": True, "payment_channel": payment_channel or "unknown", "last_payment_reference": payment_reference, "old_subscription_code": old_code, "upgrade_completed": True, "upgrade_credit_kobo": 0, "upgrade_credit": 0, "upgrade_first_debit": context["first_debit"].isoformat(), "upgrade_old_subscription_status": str(old_data.get("status") or "cancelled").lower()})
    for key in ("pending_plan", "pending_interval", "pending_upgrade_reference", "pending_upgrade_subscription_code", "upgrade_cleanup_pending", "upgrade_amount", "upgrade_amount_kobo", "upgrade", "previous_authorization_code"):
        metadata.pop(key, None)
    set_metadata(subscription, metadata)

    current_user.plan = context["new_plan"]
    current_user.subscription_status = "active"
    current_user.subscription_ends_at = period_end

    if payment_amount_kobo and payment_amount_kobo > 0:
        from app.routers.payments import record_payment_history
        await record_payment_history(db, user_id=current_user.id, subscription_id=subscription.id, reference=payment_reference, plan=context["new_plan"], interval=context["new_interval"], amount=payment_amount_kobo, currency="NGN", status="success", channel=payment_channel or None, payment_method="one_time", billing_type="one_time", event="subscription.upgrade.payment", paid_at=paid_at)

    await db.commit()
    return {"status": "success", "payment_method": "recurring", "payment_channel": payment_channel or "unknown", "plan": context["new_plan"], "interval": context["new_interval"], "subscription_status": current_user.subscription_status, "subscription_ends_at": period_end, "reference": payment_reference, "subscription_code": target_code, "old_subscription_code": old_code, "old_subscription_status": str(old_data.get("status") or "cancelled").lower(), "credit_remaining": 0, "first_debit": context["first_debit"]}


@router.post("/upgrade/quote")
async def upgrade_quote(plan: str, interval: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await get_upgrade_context(db, current_user, plan, interval)
    return {"current_plan": context["current_plan"], "current_interval": context["current_interval"], "new_plan": context["new_plan"], "new_interval": context["new_interval"], "currency": "NGN", "current_plan_price": context["current_plan_price"], "new_plan_price": context["new_plan_price"], "billing_interval": context["new_interval"], "current_period_start": context["period_start"], "current_period_ends_at": context["period_end"], "total_days": context["total_days"], "remaining_days": context["remaining_days"], "unused_value": context["unused_value"], "credit_applied": context["unused_value"], "upgrade_amount": context["upgrade_amount"], "credit_remaining": 0, "first_debit": context["first_debit"]}


@router.post("/upgrade")
async def upgrade_subscription(plan: str, interval: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    context = await get_upgrade_context(db, current_user, plan, interval)
    subscription = context["subscription"]
    metadata = context["metadata"]
    pending_reference = metadata.get("pending_upgrade_reference")
    if pending_reference:
        return {"status": "already_pending", "new_plan": context["new_plan"], "new_interval": context["new_interval"], "reference": pending_reference}

    if context["upgrade_amount_kobo"] == 0:
        reference = f"echostream_upgrade_credit_{current_user.id}_{now_utc().strftime('%Y%m%d%H%M%S%f')}"
        try:
            result = await create_target_subscription(subscription=subscription, plan=context["new_plan"], interval=context["new_interval"], authorization_code=subscription.authorization_code, first_debit=context["first_debit"])
            target_code = result["subscription_code"]
            metadata.update({"upgrade": True, "pending_plan": context["new_plan"], "pending_interval": context["new_interval"], "pending_upgrade_reference": reference, "pending_upgrade_subscription_code": target_code, "previous_plan": context["current_plan"], "previous_interval": context["current_interval"], "previous_subscription_code": subscription.paystack_subscription_code, "upgrade_amount": 0, "upgrade_amount_kobo": 0, "upgrade_credit_kobo": 0, "upgrade_first_debit": context["first_debit"].isoformat()})
            set_metadata(subscription, metadata)
            subscription.reference = reference
            subscription.last_event = "subscription.upgrade.credit_pending_cleanup"
            subscription.updated_at = now_utc()
            await db.commit()
        except PaystackError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        result = await complete_upgrade(db, current_user, subscription, context, payment_reference=reference, authorization_code=subscription.authorization_code, payment_channel=subscription.payment_method or "card")
        return {**result, "amount_due": 0}

    reference = f"echostream_upgrade_{current_user.id}_{now_utc().strftime('%Y%m%d%H%M%S%f')}"
    try:
        result = await initialize_transaction(email=current_user.email, reference=reference, callback_url=settings.PAYSTACK_CALLBACK_URL, metadata={"user_id": current_user.id, "plan": context["new_plan"], "interval": context["new_interval"], "purpose": "upgrade", "upgrade": True, "previous_plan": context["current_plan"], "previous_interval": context["current_interval"], "previous_subscription_code": subscription.paystack_subscription_code, "unused_value_kobo": context["unused_value_kobo"], "upgrade_amount_kobo": context["upgrade_amount_kobo"], "credit_remaining_kobo": 0, "first_debit": context["first_debit"].isoformat()}, amount_kobo=context["upgrade_amount_kobo"])
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = result.get("data") or {}
    reference = data.get("reference") or reference
    metadata.update({"pending_plan": context["new_plan"], "pending_interval": context["new_interval"], "pending_upgrade_reference": reference, "upgrade": True, "upgrade_amount": context["upgrade_amount"], "upgrade_amount_kobo": context["upgrade_amount_kobo"], "upgrade_credit_kobo": 0, "previous_plan": context["current_plan"], "previous_interval": context["current_interval"], "previous_subscription_code": subscription.paystack_subscription_code, "previous_authorization_code": subscription.authorization_code, "upgrade_first_debit": context["first_debit"].isoformat()})
    set_metadata(subscription, metadata)
    subscription.reference = reference
    subscription.last_event = "subscription.upgrade.payment_pending"
    subscription.updated_at = now_utc()
    await db.commit()

    return {"status": "payment_required", "current_plan": context["current_plan"], "current_interval": context["current_interval"], "new_plan": context["new_plan"], "new_interval": context["new_interval"], "upgrade_amount": context["upgrade_amount"], "currency": "NGN", "reference": reference, "authorization_url": data.get("authorization_url"), "access_code": data.get("access_code"), "first_debit": context["first_debit"], "credit_remaining": 0}


async def finalize_upgrade_reference(db: AsyncSession, reference: str, user: DBUser) -> dict:
    result = await db.execute(select(DBSubscription).where(DBSubscription.user_id == user.id))
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Payment reference not found")
    metadata = get_metadata(subscription)
    if not metadata.get("upgrade") and metadata.get("pending_upgrade_reference") != reference:
        raise HTTPException(status_code=404, detail="Payment reference is not an upgrade")
    if metadata.get("upgrade_completed") and subscription.paystack_subscription_code:
        return {"status": "success", "plan": subscription.plan, "interval": metadata.get("interval"), "subscription_code": subscription.paystack_subscription_code, "reference": reference}

    try:
        payment = await verify_transaction(reference)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    data = payment.get("data") or {}
    if str(data.get("status") or "").lower() != "success":
        return {"status": str(data.get("status") or "failed").lower(), "reference": reference}

    authorization = data.get("authorization") or {}
    authorization_code = authorization.get("authorization_code") or subscription.authorization_code
    if not authorization_code:
        raise HTTPException(status_code=502, detail="Upgrade payment did not return a reusable authorization code")
    customer = data.get("customer") or {}
    if customer.get("customer_code") and not subscription.paystack_customer_code:
        subscription.paystack_customer_code = customer["customer_code"]
    if not subscription.paystack_customer_code:
        raise HTTPException(status_code=400, detail="Paystack customer information is missing")

    plan = metadata.get("pending_plan") or metadata.get("plan")
    interval = metadata.get("pending_interval") or metadata.get("interval")
    if plan not in PAID_PLANS or interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Upgrade metadata is invalid")

    context = await get_upgrade_context(db, user, plan, interval)
    first_debit = parse_datetime(metadata.get("upgrade_first_debit"))
    if first_debit:
        context["first_debit"] = first_debit

    return await complete_upgrade(db, user, subscription, context, payment_reference=reference, authorization_code=authorization_code, payment_channel=str(data.get("channel") or "unknown").lower(), paid_at=parse_datetime(data.get("paid_at")) or now_utc(), payment_amount_kobo=int(data.get("amount") or 0))


@router.get("/verify/{reference}")
async def verify_upgrade_or_delegate(reference: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBSubscription).where(DBSubscription.user_id == current_user.id, DBSubscription.reference == reference))
    subscription = result.scalar_one_or_none()
    if subscription and get_metadata(subscription).get("upgrade"):
        return await finalize_upgrade_reference(db, reference, current_user)
    from app.routers.payment_reconciliation import verify_payment as reconciliation_verify_payment
    return await reconciliation_verify_payment(reference, current_user, db)


@router.get("/callback", include_in_schema=False)
async def upgrade_callback(reference: str | None = None, trxref: str | None = None, db: AsyncSession = Depends(get_db)):
    payment_reference = reference or trxref
    if not payment_reference:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/payment/failed")
    result = await db.execute(select(DBSubscription).where(DBSubscription.reference == payment_reference))
    subscription = result.scalar_one_or_none()
    if not subscription or not get_metadata(subscription).get("upgrade"):
        from app.routers.payment_reconciliation import payment_callback as reconciliation_payment_callback
        return await reconciliation_payment_callback(payment_reference, trxref, db)
    try:
        user_result = await db.execute(select(DBUser).where(DBUser.id == subscription.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        result = await finalize_upgrade_reference(db, payment_reference, user)
        target = "/payment/success" if result.get("status") == "success" else "/payment/failed"
    except HTTPException:
        target = "/payment/failed"
    return RedirectResponse(url=f"{settings.FRONTEND_URL}{target}?reference={payment_reference}")


@router.post("/webhook", status_code=200)
async def upgrade_webhook(request: Request, db: AsyncSession = Depends(get_db)):
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
    reference = data.get("reference")
    if event in {"charge.success", "charge.failed"} and reference:
        result = await db.execute(select(DBSubscription).where(DBSubscription.reference == reference))
        subscription = result.scalar_one_or_none()
        if subscription and get_metadata(subscription).get("upgrade"):
            if event == "charge.failed":
                return {"received": True}
            user_result = await db.execute(select(DBUser).where(DBUser.id == subscription.user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            await finalize_upgrade_reference(db, reference, user)
            return {"received": True}

    from app.routers.payment_reconciliation import paystack_webhook as reconciliation_webhook
    return await reconciliation_webhook(request, db)
