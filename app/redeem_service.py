import hashlib
import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DBRedeemCode, DBRedeemCodeRedemption, DBUser

CODE_ALPHABET = string.ascii_uppercase + string.digits


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_code(code: str) -> str:
    return "".join(code.upper().strip().split())


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def generate_code(prefix: str = "ECHO", length: int = 16) -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))
    return f"{prefix.upper()}-{raw}"


async def get_code(db: AsyncSession, code: str, *, lock: bool = False) -> DBRedeemCode | None:
    query = select(DBRedeemCode).where(DBRedeemCode.code_hash == hash_code(code))
    if lock:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def validate_code(
    db: AsyncSession,
    code: str,
    *,
    kind: str | None = None,
    user_id: int | None = None,
    lock: bool = False,
) -> DBRedeemCode:
    item = await get_code(db, code, lock=lock)
    if not item:
        raise ValueError("Invalid redeem code")
    now = now_utc()
    if not item.is_active:
        raise ValueError("This code is no longer active")
    if item.starts_at and now < item.starts_at:
        raise ValueError("This code is not active yet")
    if item.expires_at and now >= item.expires_at:
        raise ValueError("This code has expired")
    if kind and item.kind != kind:
        raise ValueError("This code cannot be used here")

    if item.max_redemptions is not None:
        consumed = await db.scalar(
            select(func.count(DBRedeemCodeRedemption.id)).where(
                DBRedeemCodeRedemption.redeem_code_id == item.id,
                DBRedeemCodeRedemption.status.in_(["pending", "consumed"]),
            )
        )
        if int(consumed or 0) >= item.max_redemptions:
            raise ValueError("This code has reached its redemption limit")

    if user_id is not None:
        existing = await db.scalar(
            select(DBRedeemCodeRedemption.id).where(
                DBRedeemCodeRedemption.redeem_code_id == item.id,
                DBRedeemCodeRedemption.user_id == user_id,
                DBRedeemCodeRedemption.status.in_(["pending", "consumed"]),
            )
        )
        if existing:
            raise ValueError("You have already used this code")

    return item


async def consume_redemption(
    db: AsyncSession,
    redemption: DBRedeemCodeRedemption,
    *,
    plan: str | None = None,
    duration_days: int | None = None,
    credit_kobo: int = 0,
    reference: str | None = None,
) -> None:
    redemption.status = "consumed"
    redemption.plan = plan
    redemption.duration_days = duration_days
    redemption.credit_kobo = credit_kobo
    redemption.checkout_reference = reference
    redemption.redeemed_at = now_utc()

    code = await db.get(DBRedeemCode, redemption.redeem_code_id, with_for_update=True)
    if code:
        code.redemption_count = (code.redemption_count or 0) + 1
        code.updated_at = now_utc()


def new_redemption(*, code: DBRedeemCode, user: DBUser, reference: str | None = None) -> DBRedeemCodeRedemption:
    return DBRedeemCodeRedemption(
        redeem_code_id=code.id,
        user_id=user.id,
        status="pending",
        checkout_reference=reference,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
