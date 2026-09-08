import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBUser
from app.paystack_service import PaystackError, charge_authorization, initialize_transaction, verify_transaction, verify_webhook_signature
from app.redeem_service import validate_code
from app.routers.upgrade import (
    PAID_PLANS,
    VALID_INTERVALS,
    add_billing_period,
    calculate_first_debit,
    complete_one_time_upgrade,
    complete_upgrade,
    finalize_upgrade_reference,
    get_pending_upgrade,
    get_upgrade_by_reference,
    get_upgrade_context,
    get_user_subscription,
    now_utc,
    parse_datetime,
)
from app.subscription_upgrade import DBSubscriptionUpgrade
from app.voucher_models import DBRedeemCode, DBRedeemCodeRedemption, DBUserCredit, DBUserCreditLedger

router = APIRouter(prefix="/payments", tags=["Payments"])


def get_upgrade_credit_reference(upgrade_reference: str) -> str:
    return f"upgrade_credit_{upgrade_reference}"


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


async def get_pending_voucher(db: AsyncSession, user_id: int, code_id: int) -> DBRedeemCodeRedemption | None:
    return await db.scalar(
        select(DBRedeemCodeRedemption).where(
            DBRedeemCodeRedemption.user_id == user_id,
            DBRedeemCodeRedemption.redeem_code_id == code_id,
            DBRedeemCodeRedemption.status == "pending",
        ).with_for_update()
    )


async def reserve_account_credit(db: AsyncSession, user_id: int, upgrade_reference: str, amount_kobo: int) -> int:
    if amount_kobo <= 0:
        return 0
    credit = await get_credit(db, user_id, lock=True)
    applied = min(max(credit.balance_kobo, 0), amount_kobo)
    if applied <= 0:
        return 0
    credit.balance_kobo -= applied
    credit.updated_at = now_utc()
    db.add(DBUserCreditLedger(
        user_id=user_id,
        amount_kobo=-applied,
        balance_after_kobo=credit.balance_kobo,
        kind="checkout_apply",
        reference=get_upgrade_credit_reference(upgrade_reference),
        metadata_json=json.dumps({"upgrade_reference": upgrade_reference}),
        created_at=now_utc(),
    ))
    return applied


async def refund_account_credit(db: AsyncSession, user_id: int, upgrade_reference: str) -> None:
    reference = get_upgrade_credit_reference(upgrade_reference)
    reservation = await db.scalar(
        select(DBUserCreditLedger).where(DBUserCreditLedger.reference == reference).with_for_update()
    )
    if not reservation or reservation.amount_kobo >= 0:
        return
    refund_reference = f"{reference}_refund"
    existing = await db.scalar(select(DBUserCreditLedger.id).where(DBUserCreditLedger.reference == refund_reference))
    if existing:
        return
    credit = await get_credit(db, user_id, lock=True)
    refund = -reservation.amount_kobo
    credit.balance_kobo += refund
    credit.updated_at = now_utc()
    db.add(DBUserCreditLedger(
        user_id=user_id,
        amount_kobo=refund,
        balance_after_kobo=credit.balance_kobo,
        kind="checkout_refund",
        reference=refund_reference,
        metadata_json=json.dumps({"upgrade_reference": upgrade_reference}),
        created_at=now_utc(),
    ))


async def settle_voucher(db: AsyncSession, upgrade: DBSubscriptionUpgrade, *, success: bool) -> None:
    redemption = await db.scalar(
        select(DBRedeemCodeRedemption).where(
            DBRedeemCodeRedemption.checkout_reference == upgrade.reference,
            DBRedeemCodeRedemption.status == "pending",
        ).with_for_update()
    )
    if not redemption:
        return
    redemption.status = "consumed" if success else "cancelled"
    redemption.redeemed_at = now_utc() if success else None
    redemption.updated_at = now_utc()
    if success:
        code = await db.scalar(select(DBRedeemCode).where(DBRedeemCode.id == redemption.redeem_code_id).with_for_update())
        if code:
            code.redemption_count += 1
            code.updated_at = now_utc()


async def finalize_and_settle(db: AsyncSession, reference: str, user: DBUser) -> dict:
    upgrade = await get_upgrade_by_reference(db, reference, lock=True)
    if not upgrade or upgrade.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment reference not found")
    result = await finalize_upgrade_reference(db, reference, user)
    success = result.get("status") == "success"
    if success:
        await settle_voucher(db, upgrade, success=True)
        await db.commit()
    return result


async def fail_upgrade(db: AsyncSession, upgrade: DBSubscriptionUpgrade, reason: str) -> None:
    if upgrade.status == "completed":
        return
    upgrade.status = "failed"
    upgrade.last_error = reason
    upgrade.updated_at = now_utc()
    await settle_voucher(db, upgrade, success=False)
    await refund_account_credit(db, upgrade.user_id, upgrade.reference)
    await db.commit()


async def build_voucher_context(db: AsyncSession, current_user: DBUser, plan: str, interval: str, voucher_code: str | None, *, lock: bool = False) -> dict:
    context = await get_upgrade_context(db, current_user, plan, interval, lock=lock)
    credit = await get_credit(db, current_user.id, lock=lock)
    account_credit_available = max(credit.balance_kobo, 0)
    voucher = None
    voucher_credit_kobo = 0

    if voucher_code:
        try:
            voucher = await validate_code(db, voucher_code, kind="voucher", user_id=current_user.id, lock=lock)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        pending = await get_pending_voucher(db, current_user.id, voucher.id)
        if pending:
            raise HTTPException(status_code=409, detail="This voucher is already being used in another checkout")
        voucher_credit_kobo = max(voucher.credit_kobo, 0)

    amount_after_existing = max(context["new_plan_price_kobo"] - context["unused_value_kobo"], 0)
    account_credit_applied = min(account_credit_available, amount_after_existing)
    amount_after_account = amount_after_existing - account_credit_applied
    voucher_credit_applied = min(voucher_credit_kobo, amount_after_account)
    total_credit_kobo = context["unused_value_kobo"] + account_credit_applied + voucher_credit_applied
    upgrade_amount_kobo = max(context["new_plan_price_kobo"] - total_credit_kobo, 0)
    first_debit, credit_duration_seconds = calculate_first_debit(
        now_utc(),
        context["new_interval"],
        total_credit_kobo,
        context["new_plan_price_kobo"],
        upgrade_amount_kobo,
    )

    context.update({
        "account_credit_available_kobo": account_credit_available,
        "account_credit_applied_kobo": account_credit_applied,
        "voucher": voucher,
        "voucher_credit_kobo": voucher_credit_kobo,
        "voucher_credit_applied_kobo": voucher_credit_applied,
        "total_credit_kobo": total_credit_kobo,
        "upgrade_amount_kobo": upgrade_amount_kobo,
        "upgrade_amount": upgrade_amount_kobo / 100,
        "credit_duration_seconds": credit_duration_seconds,
        "first_debit": first_debit,
    })
    return context


@router.post("/upgrade/quote")
async def upgrade_quote_with_voucher(
    plan: str,
    interval: str,
    voucher_code: str | None = None,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context = await build_voucher_context(db, current_user, plan, interval, voucher_code)
    return {
        "current_plan": context["current_plan"],
        "current_interval": context["current_interval"],
        "new_plan": context["new_plan"],
        "new_interval": context["new_interval"],
        "currency": "NGN",
        "current_plan_price": context["current_plan_price"],
        "new_plan_price": context["new_plan_price"],
        "billing_interval": context["new_interval"],
        "current_period_start": context["period_start"],
        "current_period_ends_at": context["period_end"],
        "total_days": context["total_days"],
        "remaining_days": context["remaining_days"],
        "unused_value": context["unused_value_kobo"] / 100,
        "account_credit_available": context["account_credit_available_kobo"] / 100,
        "account_credit_applied": context["account_credit_applied_kobo"] / 100,
        "voucher_credit_applied": context["voucher_credit_applied_kobo"] / 100,
        "credit_applied": context["total_credit_kobo"] / 100,
        "upgrade_amount": context["upgrade_amount"],
        "credit_remaining": max(context["account_credit_available_kobo"] - context["account_credit_applied_kobo"], 0) / 100,
        "first_debit": context["first_debit"],
    }


@router.post("/upgrade")
async def upgrade_subscription_with_voucher(
    plan: str,
    interval: str,
    voucher_code: str | None = None,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    context = await build_voucher_context(db, current_user, plan, interval, voucher_code, lock=True)
    subscription = context["subscription"]
    pending = await get_pending_upgrade(db, current_user.id, lock=True)

    if pending and pending.new_plan == context["new_plan"] and pending.new_interval == context["new_interval"]:
        if pending.status == "completed":
            if not pending.old_subscription_code:
                return await complete_one_time_upgrade(db, current_user, subscription, pending, payment_channel=pending.payment_channel or "card")
            return await complete_upgrade(db, current_user, subscription, pending, authorization_code=pending.new_authorization_code or subscription.authorization_code or "", payment_channel=pending.payment_channel or "card")
        if pending.upgrade_amount_kobo > 0 and pending.payment_reference:
            try:
                payment = await verify_transaction(pending.payment_reference)
                pending_status = str((payment.get("data") or {}).get("status") or "").lower()
            except PaystackError:
                pending_status = "unknown"
            if pending_status == "success":
                return await finalize_and_settle(db, pending.payment_reference, current_user)
            if pending_status not in {"failed", "abandoned", "reversed"}:
                return {"status": "already_pending", "new_plan": pending.new_plan, "new_interval": pending.new_interval, "reference": pending.payment_reference}
            await fail_upgrade(db, pending, f"Paystack payment status: {pending_status}")

    now = now_utc()
    reference = f"echostream_upgrade_{current_user.id}_{now.strftime('%Y%m%d%H%M%S%f')}"

    voucher = context.get("voucher")
    if voucher:
        existing_pending = await get_pending_voucher(db, current_user.id, voucher.id)
        if existing_pending:
            raise HTTPException(status_code=409, detail="This voucher is already being used in another checkout")
        db.add(DBRedeemCodeRedemption(
            redeem_code_id=voucher.id,
            user_id=current_user.id,
            status="pending",
            credit_kobo=context["voucher_credit_applied_kobo"],
            checkout_reference=reference,
            created_at=now,
            updated_at=now,
        ))

    account_credit_applied = await reserve_account_credit(
        db,
        current_user.id,
        reference,
        context["account_credit_applied_kobo"],
    )

    if account_credit_applied != context["account_credit_applied_kobo"]:
        context["account_credit_applied_kobo"] = account_credit_applied
        context["total_credit_kobo"] = context["unused_value_kobo"] + account_credit_applied + context["voucher_credit_applied_kobo"]
        context["upgrade_amount_kobo"] = max(context["new_plan_price_kobo"] - context["total_credit_kobo"], 0)
        context["upgrade_amount"] = context["upgrade_amount_kobo"] / 100
        context["first_debit"], context["credit_duration_seconds"] = calculate_first_debit(now, context["new_interval"], context["total_credit_kobo"], context["new_plan_price_kobo"], context["upgrade_amount_kobo"])

    upgrade = DBSubscriptionUpgrade(
        user_id=current_user.id,
        subscription_id=subscription.id,
        reference=reference,
        old_plan=context["current_plan"],
        old_interval=context["current_interval"],
        old_subscription_code=subscription.paystack_subscription_code,
        old_authorization_code=subscription.authorization_code,
        old_period_start=context["period_start"],
        old_period_end=context["period_end"],
        new_plan=context["new_plan"],
        new_interval=context["new_interval"],
        total_seconds=context["total_seconds"],
        remaining_seconds=context["remaining_seconds"],
        old_plan_price_kobo=context["current_plan_price_kobo"],
        new_plan_price_kobo=context["new_plan_price_kobo"],
        unused_value_kobo=context["total_credit_kobo"],
        upgrade_amount_kobo=context["upgrade_amount_kobo"],
        credit_duration_seconds=context["credit_duration_seconds"],
        first_debit=context["first_debit"],
        status="pending_payment" if context["upgrade_amount_kobo"] > 0 else "creating_subscription",
        created_at=now,
        updated_at=now,
    )
    db.add(upgrade)
    await db.flush()

    if context["upgrade_amount_kobo"] == 0:
        try:
            if not context["recurring"]:
                result = await complete_one_time_upgrade(db, current_user, subscription, upgrade, payment_channel=subscription.payment_method or "voucher_credit")
            else:
                result = await complete_upgrade(db, current_user, subscription, upgrade, authorization_code=subscription.authorization_code or "", payment_channel=subscription.payment_method or "voucher_credit")
            await settle_voucher(db, upgrade, success=result.get("status") == "success")
            await db.commit()
            return result
        except Exception:
            await refund_account_credit(db, current_user.id, reference)
            await settle_voucher(db, upgrade, success=False)
            await db.commit()
            raise

    txn_metadata = {
        "user_id": current_user.id,
        "purpose": "upgrade",
        "upgrade_reference": reference,
        "plan": context["new_plan"],
        "interval": context["new_interval"],
        "previous_plan": context["current_plan"],
        "previous_interval": context["current_interval"],
        "previous_subscription_code": subscription.paystack_subscription_code,
        "unused_value_kobo": context["unused_value_kobo"],
        "account_credit_applied_kobo": context["account_credit_applied_kobo"],
        "voucher_credit_applied_kobo": context["voucher_credit_applied_kobo"],
        "upgrade_amount_kobo": context["upgrade_amount_kobo"],
        "first_debit": context["first_debit"].isoformat(),
    }
    upgrade.payment_reference = reference
    upgrade.updated_at = now_utc()
    await db.commit()

    if context["recurring"] and subscription.authorization_code:
        try:
            result = await charge_authorization(
                authorization_code=subscription.authorization_code,
                email=subscription.email or current_user.email,
                amount_kobo=context["upgrade_amount_kobo"],
                reference=reference,
                metadata=txn_metadata,
            )
        except PaystackError as exc:
            await fail_upgrade(db, upgrade, str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        data = result.get("data") or {}
        upgrade.payment_reference = data.get("reference") or reference
        upgrade.payment_channel = data.get("channel") or "card"
        upgrade.updated_at = now_utc()
        await db.commit()

        payment_status = str(data.get("status") or "").lower()
        if payment_status == "success":
            return await finalize_and_settle(db, upgrade.payment_reference, current_user)

        return {
            "status": "payment_required",
            "current_plan": context["current_plan"],
            "current_interval": context["current_interval"],
            "new_plan": context["new_plan"],
            "new_interval": context["new_interval"],
            "upgrade_amount": context["upgrade_amount"],
            "currency": "NGN",
            "reference": upgrade.payment_reference,
            "first_debit": context["first_debit"],
            "credit_applied": context["total_credit_kobo"] / 100,
            "credit_remaining": max(context["account_credit_available_kobo"] - context["account_credit_applied_kobo"], 0) / 100,
        }

    try:
        result = await initialize_transaction(
            email=current_user.email,
            amount_kobo=context["upgrade_amount_kobo"],
            reference=reference,
            callback_url=settings.PAYSTACK_CALLBACK_URL,
            metadata=txn_metadata,
        )
    except PaystackError as exc:
        await fail_upgrade(db, upgrade, str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = result.get("data") or {}
    upgrade.payment_reference = data.get("reference") or reference
    upgrade.updated_at = now_utc()
    await db.commit()
    return {
        "status": "payment_required",
        "current_plan": context["current_plan"],
        "current_interval": context["current_interval"],
        "new_plan": context["new_plan"],
        "new_interval": context["new_interval"],
        "upgrade_amount": context["upgrade_amount"],
        "currency": "NGN",
        "reference": upgrade.payment_reference,
        "authorization_url": data.get("authorization_url"),
        "access_code": data.get("access_code"),
        "first_debit": context["first_debit"],
        "credit_applied": context["total_credit_kobo"] / 100,
        "credit_remaining": max(context["account_credit_available_kobo"] - context["account_credit_applied_kobo"], 0) / 100,
    }


@router.get("/verify/{reference}")
async def verify_upgrade_with_voucher(reference: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    upgrade = await get_upgrade_by_reference(db, reference)
    if upgrade and upgrade.user_id == current_user.id:
        return await finalize_and_settle(db, reference, current_user)

    # This router shadows the generic /payments/verify/{reference} route.
    # Normal non-upgrade payments must therefore delegate directly to the
    # reconciliation router instead of importing a helper that does not exist.
    from app.routers.payment_reconciliation import verify_payment as reconciliation_verify_payment
    return await reconciliation_verify_payment(reference, current_user, db)


@router.get("/callback", include_in_schema=False)
async def upgrade_callback_with_voucher(reference: str | None = None, trxref: str | None = None, db: AsyncSession = Depends(get_db)):
    payment_reference = reference or trxref
    if not payment_reference:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/payment/failed")
    upgrade = await get_upgrade_by_reference(db, payment_reference)
    if not upgrade:
        from app.routers.upgrade import upgrade_callback
        return await upgrade_callback(payment_reference, trxref, db)
    try:
        user_result = await db.execute(select(DBUser).where(DBUser.id == upgrade.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        result = await finalize_and_settle(db, payment_reference, user)
        target = "/payment/success" if result.get("status") == "success" else "/payment/failed"
    except HTTPException:
        target = "/payment/failed"
    return RedirectResponse(url=f"{settings.FRONTEND_URL}{target}?reference={payment_reference}")


@router.post("/webhook", status_code=200)
async def upgrade_webhook_with_voucher(request: Request, db: AsyncSession = Depends(get_db)):
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
        upgrade = await get_upgrade_by_reference(db, reference)
        if upgrade:
            user_result = await db.execute(select(DBUser).where(DBUser.id == upgrade.user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            if event == "charge.failed":
                if upgrade.status != "completed":
                    await fail_upgrade(db, upgrade, "Paystack charge.failed webhook")
                return {"received": True}
            await finalize_and_settle(db, reference, user)
            return {"received": True}

    from app.routers.payment_reconciliation import paystack_webhook as reconciliation_webhook
    return await reconciliation_webhook(request, db)
