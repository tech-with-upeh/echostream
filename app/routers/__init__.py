"""Router package compatibility hooks."""

from fastapi import HTTPException

from . import upgrade as _upgrade


# Paystack's successful subscription-creation response is not a pending payment.
# The historical upgrade implementation tagged it as ``ispending`` and returned
# before syncing the local subscription. Strip that marker before complete_upgrade
# sees the response, without rewriting the established upgrade router.
_original_create_target_subscription = _upgrade.create_target_subscription


async def _create_target_subscription_without_pending(*, subscription, upgrade, authorization_code: str) -> dict:
    data = await _original_create_target_subscription(
        subscription=subscription,
        upgrade=upgrade,
        authorization_code=authorization_code,
    )
    data = dict(data or {})
    data.pop("ispending", None)
    return data


_upgrade.create_target_subscription = _create_target_subscription_without_pending


async def _finalize_upgrade_reference(db, reference: str, user) -> dict:
    upgrade = await _upgrade.get_upgrade_by_reference(db, reference, lock=True)
    if not upgrade or upgrade.user_id != user.id:
        raise HTTPException(status_code=404, detail="Payment reference not found")

    subscription = await _upgrade.get_user_subscription(db, user.id, lock=True)
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if upgrade.status == "completed":
        return {
            "status": "success",
            "plan": upgrade.new_plan,
            "interval": upgrade.new_interval,
            "subscription_code": upgrade.new_subscription_code,
            "reference": upgrade.payment_reference or upgrade.reference,
            "first_debit": upgrade.first_debit,
        }

    # Zero-amount upgrades are credit/voucher funded. There is no Paystack
    # transaction to verify, so finalize immediately.
    if upgrade.upgrade_amount_kobo == 0:
        if not upgrade.old_subscription_code:
            return await _upgrade.complete_one_time_upgrade(
                db,
                user,
                subscription,
                upgrade,
                payment_channel=subscription.payment_method or "card",
            )
        return await _upgrade.complete_upgrade(
            db,
            user,
            subscription,
            upgrade,
            authorization_code=subscription.authorization_code
            or upgrade.old_authorization_code
            or "",
            payment_channel=subscription.payment_method or "card",
        )

    try:
        payment = await _upgrade.verify_transaction(upgrade.payment_reference or reference)
    except _upgrade.PaystackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data = payment.get("data") or {}
    status_value = str(data.get("status") or "failed").lower()
    if status_value != "success":
        if status_value in {"failed", "abandoned", "reversed"}:
            upgrade.status = "failed"
            upgrade.last_error = f"Paystack payment status: {status_value}"
            upgrade.updated_at = _upgrade.now_utc()
            await db.commit()
        return {"status": status_value, "reference": upgrade.payment_reference or reference}

    paid_at = _upgrade.parse_datetime(data.get("paid_at")) or _upgrade.now_utc()
    amount = int(data.get("amount") or 0)
    channel = str(data.get("channel") or "unknown").lower()

    if not upgrade.old_subscription_code:
        return await _upgrade.complete_one_time_upgrade(
            db,
            user,
            subscription,
            upgrade,
            payment_channel=channel,
            paid_at=paid_at,
            payment_amount_kobo=amount,
        )

    authorization = data.get("authorization") or {}
    authorization_code = authorization.get("authorization_code") or upgrade.old_authorization_code
    if not authorization_code:
        raise HTTPException(status_code=502, detail="Upgrade payment did not return a reusable authorization code")

    customer = data.get("customer") or {}
    if customer.get("customer_code"):
        subscription.paystack_customer_code = customer["customer_code"]
    if not subscription.paystack_customer_code:
        raise HTTPException(status_code=400, detail="Paystack customer information is missing")

    upgrade.status = "payment_success"
    upgrade.payment_amount_kobo = amount
    upgrade.payment_channel = channel
    upgrade.updated_at = _upgrade.now_utc()
    await db.commit()

    return await _upgrade.complete_upgrade(
        db,
        user,
        subscription,
        upgrade,
        authorization_code=authorization_code,
        payment_channel=channel,
        paid_at=paid_at,
        payment_amount_kobo=amount,
    )


# upgrade_voucher.py imports this helper directly from app.routers.upgrade.
_upgrade.finalize_upgrade_reference = _finalize_upgrade_reference
