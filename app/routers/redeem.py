import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models import DBSubscription, DBUser
from app.paystack_service import PaystackError, create_subscription, fetch_plan, get_plan_code, initialize_transaction, verify_transaction
from app.redeem_service import generate_code, hash_code, new_redemption, validate_code
from app.voucher_models import DBRedeemCode, DBRedeemCodeRedemption, DBUserCredit, DBUserCreditLedger

router = APIRouter(prefix="/redeem", tags=["Redeem"])
PAID_PLANS = {"essential", "pro"}
PLAN_RANK = {"starter": 0, "essential": 1, "pro": 2}
VALID_KINDS = {"subscription", "voucher"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def add_period(start: datetime, interval: str) -> datetime:
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
    days = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 31, 30, 31, 30]
    return start.replace(year=year, month=month, day=min(start.day, days[month - 1]))


async def get_credit(db: AsyncSession, user_id: int, *, lock: bool = False) -> DBUserCredit:
    query = select(DBUserCredit).where(DBUserCredit.user_id == user_id)
    if lock:
        query = query.with_for_update()
    credit = (await db.execute(query)).scalar_one_or_none()
    if credit:
        return credit
    credit = DBUserCredit(user_id=user_id, balance_kobo=0, created_at=now_utc(), updated_at=now_utc())
    db.add(credit)
    await db.flush()
    return credit


def admin_only(user: DBUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.post("")
async def redeem_code(code: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        item = await validate_code(db, code, user_id=current_user.id, lock=True)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if item.kind == "voucher":
        if item.credit_kobo <= 0:
            raise HTTPException(status_code=400, detail="This voucher has no credit value")
        credit = await get_credit(db, current_user.id, lock=True)
        credit.balance_kobo += item.credit_kobo
        credit.updated_at = now_utc()
        redemption = new_redemption(code=item, user=current_user)
        redemption.credit_kobo = item.credit_kobo
        db.add(redemption)
        item.redemption_count += 1
        item.updated_at = now_utc()
        ledger = DBUserCreditLedger(user_id=current_user.id, amount_kobo=item.credit_kobo, balance_after_kobo=credit.balance_kobo, kind="voucher_redeem", reference=f"voucher_{uuid.uuid4().hex}", redeem_code_id=item.id, created_at=now_utc())
        db.add(ledger)
        await db.commit()
        return {"success": True, "type": "voucher", "credit_added": item.credit_kobo / 100, "credit_balance": credit.balance_kobo / 100}

    plan = (item.plan or "").lower()
    if plan not in PAID_PLANS or not item.duration_days or item.duration_days <= 0:
        raise HTTPException(status_code=400, detail="Subscription code is not configured correctly")
    subscription = (await db.execute(select(DBSubscription).where(DBSubscription.user_id == current_user.id).with_for_update())).scalar_one_or_none()
    if subscription:
        metadata = {}
        if subscription.metadata_json:
            try:
                metadata = json.loads(subscription.metadata_json)
            except json.JSONDecodeError:
                metadata = {}
        if metadata.get("recurring") and subscription.paystack_subscription_code and subscription.status in {"active", "non-renewing"}:
            raise HTTPException(status_code=400, detail="Cancel or finish the current recurring subscription before redeeming a subscription code")

    if PLAN_RANK[plan] < PLAN_RANK.get(current_user.plan, 0):
        raise HTTPException(status_code=400, detail="This code is for a lower plan than your current plan")

    start = now_utc()
    if current_user.subscription_ends_at and current_user.subscription_ends_at > start:
        start = current_user.subscription_ends_at
    end = start + timedelta(days=item.duration_days)

    if not subscription:
        subscription = DBSubscription(user_id=current_user.id, plan=plan, status="active", reference=f"redeem_{uuid.uuid4().hex}", current_period_start=start, current_period_end=end, cancel_at_period_end=True, metadata_json=json.dumps({"interval": "month", "recurring": False, "source": "redeem_code", "redeem_code_id": item.id}), created_at=now_utc(), updated_at=now_utc())
        db.add(subscription)
    else:
        subscription.plan = plan
        subscription.status = "active"
        subscription.reference = f"redeem_{uuid.uuid4().hex}"
        subscription.current_period_start = start
        subscription.current_period_end = end
        subscription.cancel_at_period_end = True
        subscription.paystack_subscription_code = None
        subscription.metadata_json = json.dumps({"interval": "month", "recurring": False, "source": "redeem_code", "redeem_code_id": item.id})
        subscription.updated_at = now_utc()

    current_user.plan = plan
    current_user.subscription_status = "active"
    current_user.subscription_ends_at = end
    redemption = new_redemption(code=item, user=current_user)
    redemption.plan = plan
    redemption.duration_days = item.duration_days
    db.add(redemption)
    item.redemption_count += 1
    item.updated_at = now_utc()
    await db.commit()
    return {"success": True, "type": "subscription", "plan": plan, "starts_at": start, "expires_at": end}


@router.post("/validate")
async def validate_redeem_code(code: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        item = await validate_code(db, code, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"valid": True, "type": item.kind, "plan": item.plan, "duration_days": item.duration_days, "credit": item.credit_kobo / 100, "expires_at": item.expires_at}


@router.get("/balance")
async def credit_balance(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    credit = await get_credit(db, current_user.id)
    await db.commit()
    return {"balance": credit.balance_kobo / 100, "currency": "NGN"}


@router.post("/admin/codes")
async def create_redeem_codes(payload: dict, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    admin_only(current_user)
    kind = str(payload.get("kind", "voucher")).lower().strip()
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail="kind must be subscription or voucher")
    count = min(max(int(payload.get("count", 1)), 1), 1000)
    prefix = str(payload.get("prefix", "ECHO")).upper().strip()[:12] or "ECHO"
    max_redemptions = payload.get("max_redemptions")
    if max_redemptions is not None:
        max_redemptions = int(max_redemptions)
        if max_redemptions <= 0:
            raise HTTPException(status_code=400, detail="max_redemptions must be positive")
    duration_days = int(payload.get("duration_days", 0) or 0)
    credit_kobo = int(payload.get("credit_kobo", 0) or 0)
    plan = str(payload.get("plan", "")).lower().strip() or None
    if kind == "subscription":
        if plan not in PAID_PLANS or duration_days <= 0:
            raise HTTPException(status_code=400, detail="Subscription codes require a paid plan and positive duration_days")
        credit_kobo = 0
    else:
        if credit_kobo <= 0:
            raise HTTPException(status_code=400, detail="Voucher codes require positive credit_kobo")
        plan = None
        duration_days = 0

    starts_at = payload.get("starts_at")
    expires_at = payload.get("expires_at")
    try:
        starts_at = datetime.fromisoformat(starts_at.replace("Z", "+00:00")) if starts_at else None
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if expires_at else None
    except (AttributeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="starts_at/expires_at must be ISO timestamps") from exc

    created = []
    for _ in range(count):
        for _attempt in range(10):
            raw = generate_code(prefix)
            if not await db.scalar(select(DBRedeemCode.id).where(DBRedeemCode.code_hash == hash_code(raw))):
                break
        else:
            raise HTTPException(status_code=500, detail="Could not generate a unique redeem code")
        item = DBRedeemCode(code_hash=hash_code(raw), code_prefix=raw[: min(len(raw), len(prefix) + 1)], kind=kind, plan=plan, duration_days=duration_days or None, credit_kobo=credit_kobo, max_redemptions=max_redemptions, redemption_count=0, starts_at=starts_at, expires_at=expires_at, is_active=True, created_by=current_user.id, created_at=now_utc(), updated_at=now_utc())
        db.add(item)
        created.append(raw)
    await db.commit()
    return {"count": len(created), "codes": created, "kind": kind, "plan": plan, "duration_days": duration_days or None, "credit": credit_kobo / 100}


@router.post("/admin/{code}/disable")
async def disable_redeem_code(code: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    admin_only(current_user)
    item = await db.scalar(select(DBRedeemCode).where(DBRedeemCode.code_hash == hash_code(code)).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="Redeem code not found")
    item.is_active = False
    item.updated_at = now_utc()
    await db.commit()
    return {"success": True, "active": False}


@router.get("/checkout/quote")
async def voucher_checkout_quote(plan: str, interval: str = "month", current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    plan = plan.lower().strip()
    interval = interval.lower().strip()
    if plan not in PAID_PLANS or interval not in {"month", "year"}:
        raise HTTPException(status_code=400, detail="Invalid plan or interval")
    try:
        remote = await fetch_plan(get_plan_code(plan, interval))
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    price_kobo = int((remote.get("data") or {}).get("amount") or 0)
    credit = await get_credit(db, current_user.id)
    applied = min(max(credit.balance_kobo, 0), price_kobo)
    return {"plan": plan, "interval": interval, "price": price_kobo / 100, "credit_available": credit.balance_kobo / 100, "credit_applied": applied / 100, "amount_due": (price_kobo - applied) / 100, "currency": "NGN"}


@router.post("/checkout")
async def voucher_checkout(plan: str, interval: str = "month", current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    plan = plan.lower().strip()
    interval = interval.lower().strip()
    if plan not in PAID_PLANS or interval not in {"month", "year"}:
        raise HTTPException(status_code=400, detail="Invalid plan or interval")
    subscription = await db.scalar(select(DBSubscription).where(DBSubscription.user_id == current_user.id))
    if subscription and current_user.plan in PAID_PLANS and subscription.status in {"active", "non-renewing"}:
        raise HTTPException(status_code=400, detail="Use the upgrade flow for an active paid subscription")

    try:
        remote = await fetch_plan(get_plan_code(plan, interval))
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    price_kobo = int((remote.get("data") or {}).get("amount") or 0)
    credit = await get_credit(db, current_user.id, lock=True)
    applied = min(max(credit.balance_kobo, 0), price_kobo)
    due = price_kobo - applied
    reference = f"echostream_voucher_{current_user.id}_{uuid.uuid4().hex}"

    if due == 0:
        start = now_utc()
        end = add_period(start, interval)
        if not subscription:
            subscription = DBSubscription(user_id=current_user.id, plan=plan, status="active", reference=reference, current_period_start=start, current_period_end=end, cancel_at_period_end=True, metadata_json=json.dumps({"interval": interval, "recurring": False, "source": "voucher_credit", "voucher_credit_kobo": applied}), created_at=now_utc(), updated_at=now_utc())
            db.add(subscription)
        else:
            subscription.plan = plan
            subscription.status = "active"
            subscription.reference = reference
            subscription.current_period_start = start
            subscription.current_period_end = end
            subscription.cancel_at_period_end = True
            subscription.metadata_json = json.dumps({"interval": interval, "recurring": False, "source": "voucher_credit", "voucher_credit_kobo": applied})
            subscription.updated_at = now_utc()
        credit.balance_kobo -= applied
        credit.updated_at = now_utc()
        db.add(DBUserCreditLedger(user_id=current_user.id, amount_kobo=-applied, balance_after_kobo=credit.balance_kobo, kind="checkout_apply", reference=reference, created_at=now_utc()))
        current_user.plan = plan
        current_user.subscription_status = "active"
        current_user.subscription_ends_at = end
        await db.commit()
        return {"status": "success", "payment_method": "voucher_credit", "plan": plan, "interval": interval, "amount_paid": 0, "credit_applied": applied / 100, "subscription_ends_at": end, "reference": reference}

    result = await initialize_transaction(email=current_user.email, reference=reference, callback_url="", metadata={"user_id": current_user.id, "plan": plan, "interval": interval, "purpose": "voucher_checkout", "credit_kobo": applied}, amount_kobo=due)
    data = result.get("data") or {}
    if not data.get("authorization_url"):
        raise HTTPException(status_code=502, detail="Paystack did not return an authorization URL")
    pending = DBSubscription(user_id=current_user.id, plan=plan, status="pending", reference=reference, metadata_json=json.dumps({"interval": interval, "plan": plan, "purpose": "voucher_checkout", "recurring": True, "credit_kobo": applied, "price_kobo": price_kobo}), created_at=now_utc(), updated_at=now_utc())
    if subscription:
        pending = subscription
        pending.plan = plan
        pending.status = "pending"
        pending.reference = reference
        pending.metadata_json = json.dumps({"interval": interval, "plan": plan, "purpose": "voucher_checkout", "recurring": True, "credit_kobo": applied, "price_kobo": price_kobo})
        pending.updated_at = now_utc()
    else:
        db.add(pending)
    await db.commit()
    return {"status": "pending", "authorization_url": data["authorization_url"], "access_code": data.get("access_code"), "reference": reference, "plan": plan, "interval": interval, "amount_due": due / 100, "credit_applied": applied / 100}


@router.get("/checkout/verify/{reference}")
async def verify_voucher_checkout(reference: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    subscription = await db.scalar(select(DBSubscription).where(DBSubscription.user_id == current_user.id, DBSubscription.reference == reference).with_for_update())
    if not subscription:
        raise HTTPException(status_code=404, detail="Checkout reference not found")
    try:
        result = await verify_transaction(reference)
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    data = result.get("data") or {}
    if data.get("status") != "success":
        return {"status": data.get("status", "failed"), "reference": reference}

    metadata = {}
    try:
        metadata = json.loads(subscription.metadata_json or "{}")
    except json.JSONDecodeError:
        pass
    plan = metadata.get("plan") or subscription.plan
    interval = metadata.get("interval") or "month"
    applied = int(metadata.get("credit_kobo") or 0)
    price_kobo = int(metadata.get("price_kobo") or 0)
    customer = data.get("customer") or {}
    authorization = data.get("authorization") or {}
    customer_code = customer.get("customer_code")
    authorization_code = authorization.get("authorization_code")
    reusable = bool(authorization.get("reusable"))
    paid_at = now_utc()
    try:
        if not customer_code or not authorization_code or not reusable:
            raise PaystackError("Paystack did not return a reusable authorization for recurring checkout")
        period_end = add_period(paid_at, interval)
        target = await create_subscription(customer=customer_code, plan_code=get_plan_code(plan, interval), authorization_code=authorization_code, start_date=period_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        target_data = target.get("data") or {}
        if not target_data.get("subscription_code"):
            raise PaystackError("Paystack did not return a subscription code")
    except PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    credit = await get_credit(db, current_user.id, lock=True)
    if applied > credit.balance_kobo:
        raise HTTPException(status_code=409, detail="Voucher credit changed before checkout verification")
    credit.balance_kobo -= applied
    credit.updated_at = now_utc()
    ledger = DBUserCreditLedger(user_id=current_user.id, amount_kobo=-applied, balance_after_kobo=credit.balance_kobo, kind="checkout_apply", reference=f"credit_{reference}", created_at=now_utc())
    db.add(ledger)
    subscription.plan = plan
    subscription.status = "active"
    subscription.paystack_customer_code = customer_code
    subscription.paystack_subscription_code = target_data["subscription_code"]
    subscription.paystack_email_token = target_data.get("email_token")
    subscription.authorization_code = authorization_code
    subscription.current_period_start = paid_at
    subscription.current_period_end = period_end
    subscription.cancel_at_period_end = False
    subscription.metadata_json = json.dumps({"interval": interval, "plan": plan, "purpose": "voucher_checkout", "recurring": True, "credit_kobo": applied, "price_kobo": price_kobo, "payment_channel": data.get("channel") or "unknown"})
    subscription.updated_at = now_utc()
    current_user.plan = plan
    current_user.subscription_status = "active"
    current_user.subscription_ends_at = period_end
    await db.commit()
    return {"status": "success", "payment_method": "recurring", "plan": plan, "interval": interval, "subscription_code": target_data["subscription_code"], "reference": reference, "credit_applied": applied / 100, "amount_paid": int(data.get("amount") or 0) / 100, "subscription_ends_at": period_end}
