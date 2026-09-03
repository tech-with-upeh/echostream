"""One-off backfill: populate payment_history from Paystack's own transaction
records, for subscriptions that existed before payment history was tracked.

Safe to re-run: inserts are keyed on Paystack's transaction `reference`
(unique constraint) and use ON CONFLICT DO NOTHING, so already-recorded
transactions are skipped.

Usage:
    python -m scripts.backfill_payment_history
    python -m scripts.backfill_payment_history --dry-run
    python -m scripts.backfill_payment_history --user-id 42
"""

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DBPaymentHistory, DBSubscription
from app.paystack_service import PaystackError, fetch_customer, list_transactions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_payment_history")

PER_PAGE = 50
# Small delay between paginated Paystack calls to stay well under rate limits.
REQUEST_DELAY_SECONDS = 0.3


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


def _build_plan_code_lookup() -> dict[str, tuple[str, str]]:
    """Map every configured Paystack plan_code -> (plan, interval), so
    historical transactions can be classified the same way live ones are."""
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


def _classify_transaction(
    txn: dict[str, Any],
    plan_lookup: dict[str, tuple[str, str]],
    fallback_plan: str,
    fallback_interval: str | None,
) -> tuple[str, str | None, str]:
    """Return (plan, interval, payment_method) for a Paystack transaction."""
    plan_obj = txn.get("plan")
    plan_code = plan_obj.get("plan_code") if isinstance(plan_obj, dict) else None

    if plan_code and plan_code in plan_lookup:
        plan, interval = plan_lookup[plan_code]
        return plan, interval, "recurring"

    if plan_code:
        # A plan code Paystack knows about but we don't have configured
        # locally anymore (e.g. a retired plan) - still recurring.
        return fallback_plan, fallback_interval, "recurring"

    return fallback_plan, fallback_interval, "one_time"


async def _resolve_customer_id(customer_code: str) -> int:
    """Paystack's GET /transaction?customer= filter takes a numeric customer
    ID, not the CUS_xxx customer code - passing the code silently matches
    nothing (still HTTP 200 with an empty list). Resolve it first."""
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
        result = await list_transactions(
            customer=customer_id,
            status="success",
            page=page,
            per_page=PER_PAGE,
        )
        data = result.get("data") or []
        transactions.extend(t for t in data if isinstance(t, dict))

        meta = result.get("meta") or {}
        page_count = meta.get("pageCount") or 1
        if not data or page >= page_count:
            break
        page += 1
        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    return transactions


async def backfill_subscription(
    db,
    subscription: DBSubscription,
    plan_lookup: dict[str, tuple[str, str]],
    dry_run: bool,
) -> tuple[int, int]:
    """Returns (transactions_seen, rows_inserted)."""
    if not subscription.paystack_customer_code:
        return 0, 0

    try:
        transactions = await _fetch_all_transactions(subscription.paystack_customer_code)
    except PaystackError as exc:
        logger.warning(
            "user_id=%s customer=%s: failed to fetch transactions (%s)",
            subscription.user_id,
            subscription.paystack_customer_code,
            exc,
        )
        return 0, 0

    inserted = 0
    for txn in transactions:
        reference = txn.get("reference")
        if not reference:
            continue

        plan, interval, payment_method = _classify_transaction(
            txn,
            plan_lookup,
            fallback_plan=subscription.plan,
            fallback_interval=None,
        )
        paid_at = _parse_paystack_datetime(txn.get("paid_at")) or _parse_paystack_datetime(
            txn.get("created_at")
        )

        if dry_run:
            logger.info(
                "[dry-run] would insert user_id=%s reference=%s plan=%s/%s amount=%s",
                subscription.user_id,
                reference,
                plan,
                interval,
                txn.get("amount"),
            )
            inserted += 1
            continue

        stmt = (
            insert(DBPaymentHistory)
            .values(
                user_id=subscription.user_id,
                subscription_id=subscription.id,
                reference=reference,
                plan=plan,
                interval=interval,
                amount=txn.get("amount"),
                currency=(txn.get("currency") or "NGN").upper(),
                status="success",
                channel=txn.get("channel"),
                payment_method=payment_method,
                event="backfill",
                paid_at=paid_at,
                created_at=_utcnow(),
            )
            .on_conflict_do_nothing(index_elements=[DBPaymentHistory.reference])
            .returning(DBPaymentHistory.id)
        )
        result = await db.execute(stmt)
        if result.first() is not None:
            inserted += 1

    if not dry_run:
        await db.commit()

    return len(transactions), inserted


async def run(dry_run: bool = False, user_id: int | None = None) -> None:
    plan_lookup = _build_plan_code_lookup()

    async with AsyncSessionLocal() as db:
        query = select(DBSubscription).where(DBSubscription.paystack_customer_code.is_not(None))
        if user_id is not None:
            query = query.where(DBSubscription.user_id == user_id)
        subscriptions = (await db.execute(query)).scalars().all()

    logger.info("Found %d subscription(s) with a Paystack customer code", len(subscriptions))

    total_seen = 0
    total_inserted = 0
    for subscription in subscriptions:
        async with AsyncSessionLocal() as db:
            # Re-attach within this session's identity map.
            subscription = await db.get(DBSubscription, subscription.id)
            seen, inserted = await backfill_subscription(db, subscription, plan_lookup, dry_run)
        total_seen += seen
        total_inserted += inserted
        if seen:
            logger.info(
                "user_id=%s: %d transaction(s) seen, %d new row(s) inserted",
                subscription.user_id,
                seen,
                inserted,
            )
        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    logger.info(
        "Backfill complete: %d transaction(s) seen across all users, %d new row(s) inserted%s",
        total_seen,
        total_inserted,
        " (dry run, nothing written)" if dry_run else "",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and log what would be inserted without writing to the database.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Only backfill this user's subscription (for testing before a full run).",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, user_id=args.user_id))


if __name__ == "__main__":
    main()