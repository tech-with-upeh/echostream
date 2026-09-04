"""Backfill payment_history from Paystack transaction history."""

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DBPaymentHistory, DBSubscription
from app.paystack_service import PaystackError, fetch_customer, fetch_customer_subscriptions_by_code, list_transactions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_payment_history")

PER_PAGE = 50
REQUEST_DELAY_SECONDS = 0.3
VALID_INTERVALS = {"month", "year"}
RECURRING_CHANNELS = {"card", "direct_debit"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_paystack_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _metadata(txn: dict[str, Any]) -> dict[str, Any]:
    value = txn.get("metadata")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def _subscription_interval(subscription: DBSubscription) -> str | None:
    if not subscription.metadata_json:
        return None
    try:
        value = json.loads(subscription.metadata_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    interval = value.get("interval")
    return interval if interval in VALID_INTERVALS else None


def _map_paystack_interval(value: Any) -> str | None:
    return {"annually": "year", "monthly": "month"}.get(value)


def _build_plan_code_lookup() -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    pairs = [
        (settings.PAYSTACK_ESSENTIAL_MONTHLY_PLAN_CODE, "essential", "month"),
        (settings.PAYSTACK_ESSENTIAL_PLAN_CODE, "essential", "month"),
        (settings.PAYSTACK_ESSENTIAL_YEARLY_PLAN_CODE, "essential", "year"),
        (settings.PAYSTACK_PRO_MONTHLY_PLAN_CODE, "pro", "month"),
        (settings.PAYSTACK_PRO_PLAN_CODE, "pro", "month"),
        (settings.PAYSTACK_PRO_YEARLY_PLAN_CODE, "pro", "year"),
    ]
    for code, plan, interval in pairs:
        if code:
            lookup[code] = (plan, interval)
    return lookup


async def _resolve_customer_id(customer_code: str) -> int:
    response = await fetch_customer(customer_code)
    customer = response.get("data") or {}
    customer_id = customer.get("id")
    if not customer_id:
        raise PaystackError(f"Paystack customer {customer_code} has no numeric id")
    return int(customer_id)


async def _fetch_all_transactions(customer_code: str) -> list[dict[str, Any]]:
    customer_id = await _resolve_customer_id(customer_code)
    transactions: list[dict[str, Any]] = []
    page = 1
    while True:
        result = await list_transactions(customer=customer_id, page=page, per_page=PER_PAGE)
        data = result.get("data") or []
        transactions.extend(item for item in data if isinstance(item, dict))
        meta = result.get("meta") or {}
        page_count = meta.get("pageCount") or 1
        if not data or page >= page_count:
            break
        page += 1
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
    return transactions


async def _build_recurring_authorization_map(customer_code: str, plan_lookup: dict[str, tuple[str, str]]) -> dict[str, tuple[str | None, str | None]]:
    try:
        response = await fetch_customer_subscriptions_by_code(customer_code)
    except PaystackError as exc:
        logger.warning("customer=%s: unable to fetch subscriptions: %s", customer_code, exc)
        return {}

    result: dict[str, tuple[str | None, str | None]] = {}
    for subscription in response.get("data") or []:
        if not isinstance(subscription, dict) or str(subscription.get("status") or "").lower() not in {"active", "non-renewing"}:
            continue
        authorization = subscription.get("authorization") or {}
        if not isinstance(authorization, dict):
            continue
        auth_code = authorization.get("authorization_code")
        if not auth_code:
            continue
        plan_obj = subscription.get("plan") or {}
        if not isinstance(plan_obj, dict):
            plan_obj = {}
        plan_code = plan_obj.get("plan_code")
        result[auth_code] = plan_lookup.get(plan_code, (None, _map_paystack_interval(plan_obj.get("interval"))))
    return result


def _classify_transaction(txn: dict[str, Any], recurring_map: dict[str, tuple[str | None, str | None]], plan_lookup: dict[str, tuple[str, str]], fallback_plan: str, fallback_interval: str | None) -> tuple[str, str | None, str]:
    metadata = _metadata(txn)
    metadata_plan = metadata.get("plan")
    metadata_interval = metadata.get("interval")
    authorization = txn.get("authorization") or {}
    auth_code = authorization.get("authorization_code") if isinstance(authorization, dict) else None
    channel = str(txn.get("channel") or "").lower().strip()

    billing_type = "recurring" if channel in RECURRING_CHANNELS else "one_time"
    plan = str(metadata_plan or fallback_plan)
    interval = metadata_interval if metadata_interval in VALID_INTERVALS else fallback_interval

    if auth_code and auth_code in recurring_map:
        mapped_plan, mapped_interval = recurring_map[auth_code]
        plan = str(metadata_plan or mapped_plan or fallback_plan)
        interval = metadata_interval if metadata_interval in VALID_INTERVALS else (mapped_interval or fallback_interval)
        billing_type = "recurring"

    plan_obj = txn.get("plan") or {}
    if isinstance(plan_obj, dict):
        plan_code = plan_obj.get("plan_code")
        if plan_code in plan_lookup:
            mapped_plan, mapped_interval = plan_lookup[plan_code]
            plan = str(metadata_plan or mapped_plan)
            if interval not in VALID_INTERVALS:
                interval = mapped_interval
        if interval not in VALID_INTERVALS:
            interval = _map_paystack_interval(plan_obj.get("interval")) or interval

    return plan, interval if interval in VALID_INTERVALS else None, billing_type


def _transaction_user_id(txn: dict[str, Any]) -> int | None:
    value = _metadata(txn).get("user_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _payment_method_details(txn: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    authorization = txn.get("authorization") or {}
    if not isinstance(authorization, dict):
        authorization = {}
    method = str(txn.get("channel") or authorization.get("channel") or "").lower().strip() or None
    brand = str(authorization.get("brand") or authorization.get("card_type") or "").strip() or None
    last4 = str(authorization.get("last4") or "").strip() or None
    return method, brand, last4


async def backfill_subscription(db, subscription: DBSubscription, plan_lookup: dict[str, tuple[str, str]], dry_run: bool) -> tuple[int, int]:
    if not subscription.paystack_customer_code:
        return 0, 0
    try:
        transactions = await _fetch_all_transactions(subscription.paystack_customer_code)
        recurring_map = await _build_recurring_authorization_map(subscription.paystack_customer_code, plan_lookup)
    except PaystackError as exc:
        logger.warning("user_id=%s customer=%s: failed to fetch Paystack history: %s", subscription.user_id, subscription.paystack_customer_code, exc)
        return 0, 0

    local_interval = _subscription_interval(subscription)
    written = 0

    for txn in transactions:
        reference = txn.get("reference")
        if not reference:
            continue
        txn_user_id = _transaction_user_id(txn)
        if txn_user_id is not None and txn_user_id != subscription.user_id:
            logger.warning("customer=%s reference=%s: metadata user_id=%s does not match subscription user_id=%s; skipping", subscription.paystack_customer_code, reference, txn_user_id, subscription.user_id)
            continue

        plan, interval, billing_type = _classify_transaction(txn, recurring_map, plan_lookup, subscription.plan, local_interval)
        status = str(txn.get("status") or "unknown").lower()
        created_at = _parse_paystack_datetime(txn.get("created_at"))
        paid_at = _parse_paystack_datetime(txn.get("paid_at"))
        method, method_brand, method_last4 = _payment_method_details(txn)

        if dry_run:
            logger.info("[dry-run] user_id=%s reference=%s status=%s plan=%s interval=%s billing_type=%s method=%s brand=%s last4=%s", subscription.user_id, reference, status, plan, interval, billing_type, method, method_brand, method_last4)
            written += 1
            continue

        values = {
            "user_id": subscription.user_id,
            "subscription_id": subscription.id,
            "reference": reference,
            "plan": plan,
            "interval": interval,
            "amount": int(txn.get("amount") or 0) / 100,
            "currency": (txn.get("currency") or "NGN").upper(),
            "status": status,
            "method": method,
            "method_brand": method_brand,
            "method_last4": method_last4,
            "billing_type": billing_type,
            "event": "backfill",
            "paid_at": paid_at,
            "created_at": created_at or _utcnow(),
        }
        stmt = insert(DBPaymentHistory).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DBPaymentHistory.reference],
            set_={
                "user_id": stmt.excluded.user_id,
                "subscription_id": stmt.excluded.subscription_id,
                "status": stmt.excluded.status,
                "plan": stmt.excluded.plan,
                "interval": stmt.excluded.interval,
                "amount": stmt.excluded.amount,
                "currency": stmt.excluded.currency,
                "method": stmt.excluded.method,
                "method_brand": stmt.excluded.method_brand,
                "method_last4": stmt.excluded.method_last4,
                "billing_type": stmt.excluded.billing_type,
                "event": stmt.excluded.event,
                "paid_at": stmt.excluded.paid_at,
            },
        )
        result = await db.execute(stmt)
        if result.rowcount:
            written += 1

    if not dry_run:
        await db.commit()
    return len(transactions), written


async def run(dry_run: bool = False, user_id: int | None = None) -> None:
    plan_lookup = _build_plan_code_lookup()
    async with AsyncSessionLocal() as db:
        query = select(DBSubscription).where(DBSubscription.paystack_customer_code.is_not(None))
        if user_id is not None:
            query = query.where(DBSubscription.user_id == user_id)
        subscriptions = (await db.execute(query)).scalars().all()

    logger.info("Found %d subscription(s) with a Paystack customer code", len(subscriptions))
    total_seen = 0
    total_written = 0
    for subscription in subscriptions:
        async with AsyncSessionLocal() as db:
            current = await db.get(DBSubscription, subscription.id)
            if current is None:
                continue
            seen, written = await backfill_subscription(db, current, plan_lookup, dry_run)
        total_seen += seen
        total_written += written
        logger.info("user_id=%s: %d transaction(s) seen, %d row(s) written/corrected", subscription.user_id, seen, written)
        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    logger.info("Backfill complete: %d transaction(s) seen, %d row(s) written/corrected%s", total_seen, total_written, " (dry run, nothing written)" if dry_run else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--user-id", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, user_id=args.user_id))


if __name__ == "__main__":
    main()
