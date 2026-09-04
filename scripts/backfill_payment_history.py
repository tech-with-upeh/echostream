"""One-off backfill: populate payment_history from Paystack's own transaction
records, for subscriptions that existed before payment history was tracked.

Safe to re-run: inserts are keyed on Paystack's transaction `reference`
(unique constraint). If a row for that reference doesn't exist yet, it's
inserted. If it already exists as "one_time" (e.g. from the old
verify_payment bug that couldn't see the real subscription_code) and
Paystack's own record shows it's actually "recurring", this corrects it in
place. It never downgrades an already-correct "recurring" row, and never
touches anything else about an existing row.

Usage:
    python -m scripts.backfill_payment_history
    python -m scripts.backfill_payment_history --dry-run
    python -m scripts.backfill_payment_history --user-id 42
"""

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
from app.paystack_service import (
    PaystackError,
    fetch_customer,
    fetch_customer_subscriptions_by_code,
    list_transactions,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_payment_history")

PER_PAGE = 50
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


def _subscription_interval(subscription: DBSubscription) -> str | None:
    """Read the interval our own app already recorded on this subscription
    (set by verify_payment/webhooks into metadata_json), for use as the
    final fallback when Paystack's own transaction/subscription data
    doesn't resolve one - e.g. an old plan code no longer configured
    locally, or a subscription record Paystack's side is thin on."""
    if not subscription.metadata_json:
        return None
    try:
        value = json.loads(subscription.metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    interval = value.get("interval")
    return interval if interval in {"month", "year"} else None


def _map_paystack_interval(paystack_interval: str | None) -> str | None:
    """Map Paystack's plan interval vocabulary (hourly, daily, weekly,
    monthly, quarterly, biannually, annually) onto our own two-value
    interval field. We only ever create monthly/yearly plans ourselves, so
    "annually" is the only value that should map to "year" - everything
    else defaults to "month" as the closer approximation."""
    if not paystack_interval:
        return None
    return "year" if paystack_interval == "annually" else "month"


def _build_plan_code_lookup() -> dict[str, tuple[str, str]]:
    """Map every configured Paystack plan_code -> (plan, interval)."""
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


async def _build_recurring_authorization_map(
    customer_code: str,
    plan_lookup: dict[str, tuple[str, str]],
) -> dict[str, tuple[str | None, str | None]]:
    """Map authorization_code -> (plan, interval) for every one of this
    customer's real Paystack subscriptions.

    This is the reliable signal. Paystack's /transaction (list/verify)
    response frequently reports an empty `plan` object even for a charge
    that funded a genuine subscription - the plan/subscription link only
    shows up reliably on the /subscription resource itself. But every
    subscription's `authorization.authorization_code` matches the exact
    authorization used for its charges, including the very first one, so
    matching transactions to subscriptions by authorization_code (rather
    than by the transaction's own, often-empty plan field) is what actually
    identifies which transactions were recurring.
    """
    recurring_map: dict[str, tuple[str | None, str | None]] = {}
    try:
        subs_result = await fetch_customer_subscriptions_by_code(customer_code)
    except PaystackError:
        return recurring_map

    for sub in subs_result.get("data") or []:
        if not isinstance(sub, dict):
            continue
        auth = sub.get("authorization") or {}
        auth_code = auth.get("authorization_code") if isinstance(auth, dict) else None
        if not auth_code:
            continue

        plan_obj = sub.get("plan") or {}
        plan_code = plan_obj.get("plan_code") if isinstance(plan_obj, dict) else None

        if plan_code and plan_code in plan_lookup:
            recurring_map[auth_code] = plan_lookup[plan_code]
        else:
            paystack_interval = plan_obj.get("interval") if isinstance(plan_obj, dict) else None
            recurring_map[auth_code] = (None, _map_paystack_interval(paystack_interval))
    print(">>>>>>>", recurring_map)
    return recurring_map


def _classify_transaction(
    txn: dict[str, Any],
    recurring_map: dict[str, tuple[str | None, str | None]],
    plan_lookup: dict[str, tuple[str, str]],
    fallback_plan: str,
    fallback_interval: str | None,
) -> tuple[str, str | None, str]:
    """Return (plan, interval, payment_method) for a Paystack transaction."""
    plan_obj = txn.get("metadata")
    plan_code = plan_obj.get("plan")

    if plan_obj and plan_code:
        interval = plan_obj.get("interval")
        return plan_code, interval, "recurring"

    auth = txn.get("authorization") or {}
    auth_code = auth.get("authorization_code") if isinstance(auth, dict) else None
    if auth_code and auth_code in recurring_map:
        mapped_plan, mapped_interval = recurring_map[auth_code]
        return (mapped_plan or fallback_plan), (mapped_interval or fallback_interval), "recurring"

    if plan_code:
        # Paystack told us there's a plan, just not one we recognize locally.
        return fallback_plan, fallback_interval, "recurring"

    return fallback_plan, fallback_interval, "one_time"


async def _resolve_customer_id(customer_code: str) -> int:
    """Resolve a Paystack customer code to the numeric customer id required
    by Paystack's transaction customer filter."""
    response = await fetch_customer(customer_code)
    customer = response.get("data") or {}
    customer_id = customer.get("id")
    if not customer_id:
        raise PaystackError(f"Paystack customer {customer_code} has no numeric id")
    return int(customer_id)


async def _fetch_all_transactions(customer_code: str) -> list[dict[str, Any]]:
    """Fetch every transaction for a customer, regardless of status."""
    customer_id = await _resolve_customer_id(customer_code)
    transactions: list[dict[str, Any]] = []
    page = 1

    while True:
        # Do NOT pass status="success" here. Paystack's transaction endpoint
        # otherwise filters the historical dataset to successful payments only.
        result = await list_transactions(
            customer=customer_id,
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

    recurring_map = await _build_recurring_authorization_map(
        subscription.paystack_customer_code, plan_lookup
    )
    if dry_run:
        logger.info(
            "user_id=%s customer=%s: found %d subscription authorization(s) to match against: %s",
            subscription.user_id,
            subscription.paystack_customer_code,
            len(recurring_map),
            list(recurring_map.keys()),
        )

    inserted = 0
    for txn in transactions:
        reference = txn.get("reference")
        if not reference:
            continue

        plan, interval, payment_method = _classify_transaction(
            txn,
            recurring_map,
            plan_lookup,
            fallback_plan=subscription.plan,
            fallback_interval=_subscription_interval(subscription),
        )
        paid_at = _parse_paystack_datetime(txn.get("paid_at")) or _parse_paystack_datetime(
            txn.get("created_at")
        )
        transaction_status = str(txn.get("status") or "unknown").lower()
        channel = str(txn.get("channel") or "").lower() or None

        if dry_run:
            logger.info(
                "[dry-run] would insert user_id=%s reference=%s status=%s plan=%s/%s method=%s amount=%s",
                subscription.user_id,
                reference,
                transaction_status,
                plan,
                interval,
                payment_method,
                txn.get("amount"),
            )
            inserted += 1
            continue

        insert_stmt = insert(DBPaymentHistory).values(
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            reference=reference,
            plan=plan,
            interval=interval,
            amount=txn.get("amount"),
            currency=(txn.get("currency") or "NGN").upper(),
            status=transaction_status,
            channel=channel,
            payment_method=payment_method,
            billing_type=payment_method,
            event="backfill",
            paid_at=paid_at,
            created_at=_utcnow(),
        )
        # A row for this reference may already exist, written as "one_time"
        # by the old verify_payment bug (which had no way to see the real
        # subscription_code). Paystack's own transaction/plan data here is
        # authoritative, so let it upgrade the row instead of being skipped -
        # this never downgrades an already-correct "recurring" row.
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[DBPaymentHistory.reference],
            set_={"payment_method": insert_stmt.excluded.payment_method, "billing_type": insert_stmt.excluded.billing_type},
            where=(DBPaymentHistory.payment_method == "one_time")
            & (insert_stmt.excluded.payment_method == "recurring"),
        )
        result = await db.execute(stmt)
        if result.rowcount:
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
            subscription = await db.get(DBSubscription, subscription.id)
            seen, inserted = await backfill_subscription(db, subscription, plan_lookup, dry_run)
        total_seen += seen
        total_inserted += inserted
        if seen:
            logger.info(
                "user_id=%s: %d transaction(s) seen, %d row(s) written/corrected",
                subscription.user_id,
                seen,
                inserted,
            )
        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    logger.info(
        "Backfill complete: %d transaction(s) seen across all users, %d row(s) written/corrected%s",
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
