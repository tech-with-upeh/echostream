import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

# NOTE: this assumes app.database exposes the AsyncEngine as `engine`.
# If yours has a different name, change it here.
from app.database import AsyncSessionLocal, engine
from app.models import DBGiftCatalogSync, DBTikTokGift
from app.r2_storage import (
    R2StorageError,
    upload_gift_image,
    upload_generic_gift_image,
)


logger = logging.getLogger(__name__)


EULER_GIFT_CATALOG_PATH = "/webcast/gifts/catalog"

EULER_PAGE_SIZE = 100

EULER_MAX_PAGES = 1000


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

# Same name as before, so it hashes to the same advisory lock key.
GIFT_SYNC_LOCK_NAME = "echostream_gift_catalog_sync"


# ---------------------------------------------------------------------------
# Partial-response protection
# ---------------------------------------------------------------------------

# If Euler returns fewer than this fraction of the previously synced gift
# count, the response is treated as truncated and the sync is aborted
# before anything is written or deactivated.
EULER_MIN_CATALOG_RATIO = float(os.getenv("EULER_MIN_CATALOG_RATIO", "0.5"))

# Escape hatch for when the catalog genuinely shrinks a lot.
# Set EULER_ALLOW_CATALOG_SHRINK=1 for one run, then unset it.
EULER_ALLOW_CATALOG_SHRINK = os.getenv("EULER_ALLOW_CATALOG_SHRINK", "").lower() in {
    "1",
    "true",
    "yes",
}


# ---------------------------------------------------------------------------
# Generic image detection
# ---------------------------------------------------------------------------

# Must match the key used in r2_storage.upload_generic_gift_image:
#   gift-images/generic-tiktok.<ext>
GENERIC_IMAGE_MARKER = "gift-images/generic-tiktok."


def _is_generic_image_url(url: str | None) -> bool:
    return bool(url) and GENERIC_IMAGE_MARKER in url


# Change these if your files live somewhere else.
BASE_DIR = Path(__file__).resolve().parent.parent

BEETGAMES_GIFT_IMAGES_DIR = Path(
    os.getenv(
        "BEETGAMES_GIFT_IMAGES_DIR",
        BASE_DIR / "tiktok-gift-icons",
    )
)

GENERIC_TIKTOK_ICON_PATH = Path(
    os.getenv(
        "GENERIC_TIKTOK_ICON_PATH",
        BASE_DIR / "tiktok-gift-icons/tik-tok.png",
    )
)


class CatalogShrinkError(RuntimeError):
    """Raised when Euler's catalog looks truncated compared to the last sync."""


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""

    value = str(value).strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(r"\s+", " ", value).strip()


def _slugify_gift_name(name: str) -> str:
    """
    Convert an Euler gift name to the BeetGames-style slug.

    Example:
        Rose             -> rose
        10/10            -> 10-10
        Super Heart      -> super-heart
    """

    value = str(name).strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    value = re.sub(
        r"-+",
        "-",
        value,
    )

    return value.strip("-")


def _extract_gifts(payload: Any) -> list[dict[str, Any]]:
    """
    Euler can return either:

        [...]

    or:

        {"gifts": [...]}

    or nested variants.
    """

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    gifts = payload.get("gifts")

    if isinstance(gifts, list):
        return [item for item in gifts if isinstance(item, dict)]

    for container_key in ("data", "result"):
        container = payload.get(container_key)

        if isinstance(container, dict):
            gifts = container.get("gifts")

            if isinstance(gifts, list):
                return [item for item in gifts if isinstance(item, dict)]

    return []


def _get_total_pages(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None

    for key in ("totalPages", "total_pages"):
        value = payload.get(key)

        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

    for container_key in ("data", "result"):
        container = payload.get(container_key)

        if not isinstance(container, dict):
            continue

        for key in ("totalPages", "total_pages"):
            value = container.get(key)

            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

    return None


def _normalize(gift: dict[str, Any]) -> dict[str, Any] | None:
    gift_id = gift.get("giftId") or gift.get("gift_id") or gift.get("id")

    name = gift.get("giftName") or gift.get("gift_name") or gift.get("name")

    diamond_count = (
        gift.get("diamondCount")
        if gift.get("diamondCount") is not None
        else gift.get("diamond_count")
    )

    gift_type = (
        gift.get("giftType")
        if gift.get("giftType") is not None
        else gift.get("gift_type")
    )

    if gift_id is None or name is None:
        return None

    try:
        gift_id = str(gift_id)
    except Exception:
        return None

    try:
        diamond_count = int(diamond_count or 0)
    except (TypeError, ValueError):
        diamond_count = 0

    try:
        gift_type = int(gift_type or 0)
    except (TypeError, ValueError):
        gift_type = 0

    return {
        "id": gift_id,
        "name": str(name).strip(),
        "diamond_count": diamond_count,
        "type": gift_type,
    }


async def _fetch_euler_catalog() -> list[dict[str, Any]]:
    """
    Fetch every Euler gift catalog page.

    Euler's catalog route is paginated, so this keeps requesting
    pages until totalPages is reached or the returned page is
    smaller than the requested page size.

    Raises if a page comes back empty before totalPages is reached,
    because that means the catalog we'd end up with is incomplete.
    """

    if not settings.EULER_GIFT_CATALOG_API_KEY:
        raise RuntimeError("EULER_GIFT_CATALOG_API_KEY is not configured.")

    base_url = settings.EULER_GIFT_CATALOG_BASE_URL.rstrip("/")

    headers = {
        "X-API-Key": settings.EULER_GIFT_CATALOG_API_KEY,
        "Authorization": (f"Bearer {settings.EULER_GIFT_CATALOG_API_KEY}"),
    }

    all_gifts: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=30.0,
    ) as client:

        page = 1
        total_pages: int | None = None

        while True:
            if page > EULER_MAX_PAGES:
                raise RuntimeError(
                    "Euler catalog exceeded the maximum page safety limit."
                )

            response = await client.get(
                f"{base_url}{EULER_GIFT_CATALOG_PATH}",
                headers=headers,
                params={
                    "pageNumber": page,
                    "pageSize": EULER_PAGE_SIZE,
                },
            )

            response.raise_for_status()

            payload = response.json()

            page_gifts = _extract_gifts(payload)

            total_pages = total_pages or _get_total_pages(payload)

            logger.info(
                "Fetched Euler gift catalog page %s%s: %s gifts",
                page,
                (f"/{total_pages}" if total_pages else ""),
                len(page_gifts),
            )

            # An empty page before the advertised last page means the
            # catalog is incomplete. Abort instead of syncing a partial list.
            if not page_gifts and total_pages is not None and page < total_pages:
                raise RuntimeError(
                    f"Euler returned an empty catalog page {page} "
                    f"but reported {total_pages} total pages."
                )

            all_gifts.extend(page_gifts)

            if total_pages is not None:
                if page >= total_pages:
                    break

            elif len(page_gifts) < EULER_PAGE_SIZE:
                break

            page += 1

    normalized: list[dict[str, Any]] = []

    # Important:
    # do NOT deduplicate by gift name because Euler can contain
    # multiple gifts with the same name.
    seen_ids: set[str] = set()

    for gift in all_gifts:
        item = _normalize(gift)

        if item is None:
            continue

        if item["id"] in seen_ids:
            continue

        seen_ids.add(item["id"])
        normalized.append(item)

    if not normalized:
        raise RuntimeError("Euler returned an empty gift catalog.")

    logger.info(
        "Euler catalog contains %s unique gifts",
        len(normalized),
    )

    return normalized


def _check_catalog_size(
    gifts: list[dict[str, Any]],
    previous_count: int | None,
) -> None:
    """
    Refuse to apply a catalog that is suspiciously smaller than the number
    of gifts currently active in the database. Without this, a truncated
    Euler response would mark every missing gift as inactive.
    """

    if not previous_count or previous_count <= 0:
        return  # first sync, nothing to compare against

    new_count = len(gifts)
    minimum = int(previous_count * EULER_MIN_CATALOG_RATIO)

    if new_count >= minimum:
        return

    if EULER_ALLOW_CATALOG_SHRINK:
        logger.warning(
            "Euler catalog shrank from %s to %s gifts (below %.0f%% threshold), "
            "but EULER_ALLOW_CATALOG_SHRINK is set. Continuing.",
            previous_count,
            new_count,
            EULER_MIN_CATALOG_RATIO * 100,
        )
        return

    raise CatalogShrinkError(
        f"Euler returned {new_count} gifts but the database has "
        f"{previous_count} active gifts (minimum accepted: {minimum}). "
        "Treating this as a partial response; nothing was changed. "
        "Set EULER_ALLOW_CATALOG_SHRINK=1 if the shrink is real."
    )


def _fingerprint(
    gifts: list[dict[str, Any]],
) -> str:
    canonical = json.dumps(
        sorted(
            gifts,
            key=lambda gift: gift["id"],
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_beetgames_image(
    gift: dict[str, Any],
) -> Path | None:
    """
    BeetGames files use:

        <slug>-<amount>-coins.webp

    Example:

        rose-1-coins.webp
        10-10-1-coins.webp
    """

    slug = _slugify_gift_name(gift["name"])

    amount = gift["diamond_count"]

    filename = f"{slug}-{amount}-coins.webp"

    path = BEETGAMES_GIFT_IMAGES_DIR / filename

    if path.is_file():
        return path

    return None


def _read_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Failed to read gift image: {path}") from exc


def _get_image_metadata(
    path: Path,
) -> tuple[str, str]:
    suffix = path.suffix.lower()

    if suffix == ".webp":
        return "webp", "image/webp"

    if suffix == ".png":
        return "png", "image/png"

    if suffix in {".jpg", ".jpeg"}:
        return "jpg", "image/jpeg"

    raise RuntimeError(f"Unsupported gift image format: {path}")


async def _upload_generic_image() -> str:
    if not GENERIC_TIKTOK_ICON_PATH.is_file():
        raise RuntimeError(
            "Generic TikTok fallback image does not exist: "
            f"{GENERIC_TIKTOK_ICON_PATH}"
        )

    image_bytes = await asyncio.to_thread(
        _read_file,
        GENERIC_TIKTOK_ICON_PATH,
    )

    extension, content_type = _get_image_metadata(GENERIC_TIKTOK_ICON_PATH)

    return await upload_generic_gift_image(
        image_bytes,
        extension=extension,
        content_type=content_type,
    )


async def _sync_gift_images(
    db: AsyncSession,
    gifts: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Give every Euler gift a stable R2 image URL.

    Priority:

    1. BeetGames WebP matching the gift name + diamond count.
    2. Shared generic TikTok PNG.

    Gifts that already have a real (non-generic) image are left
    untouched so scheduled syncs don't re-upload every image.

    Gifts that only have the generic fallback are re-checked on every
    sync, so a BeetGames image added later replaces the generic one.
    """

    logger.info(
        "Gift image sources: beetgames_dir=%s (exists=%s), generic_icon=%s (exists=%s)",
        BEETGAMES_GIFT_IMAGES_DIR.resolve(),
        BEETGAMES_GIFT_IMAGES_DIR.is_dir(),
        GENERIC_TIKTOK_ICON_PATH.resolve(),
        GENERIC_TIKTOK_ICON_PATH.is_file(),
    )

    if not GENERIC_TIKTOK_ICON_PATH.is_file():
        logger.error(
            "Generic TikTok icon not found at %s; gifts without a BeetGames "
            "image will fail. Set GENERIC_TIKTOK_ICON_PATH or fix BASE_DIR.",
            GENERIC_TIKTOK_ICON_PATH.resolve(),
        )

    gift_ids = [gift["id"] for gift in gifts]

    result = await db.execute(
        select(DBTikTokGift).where(DBTikTokGift.tiktok_gift_id.in_(gift_ids))
    )

    db_gifts = {str(gift.tiktok_gift_id): gift for gift in result.scalars().all()}

    generic_url: str | None = None

    uploaded = 0
    upgraded = 0
    reused = 0
    fallback = 0
    failed = 0

    for gift in gifts:
        gift_id = gift["id"]

        db_gift = db_gifts.get(gift_id)

        if db_gift is None:
            logger.warning(
                "Gift %s was not found after catalog sync",
                gift_id,
            )
            continue

        current_url = db_gift.image_url

        # Already has a real image: leave it alone.
        if current_url and not _is_generic_image_url(current_url):
            reused += 1
            continue

        beetgames_path = _find_beetgames_image(gift)

        # Already on the generic image and there is still nothing better.
        if current_url and beetgames_path is None:
            reused += 1
            continue

        try:
            if beetgames_path is not None:
                image_bytes = await asyncio.to_thread(
                    _read_file,
                    beetgames_path,
                )

                extension, content_type = _get_image_metadata(beetgames_path)

                image_url = await upload_gift_image(
                    image_bytes,
                    gift_id=gift_id,
                    extension=extension,
                    content_type=content_type,
                )

                if current_url:
                    upgraded += 1
                    logger.info(
                        "Upgraded generic image to BeetGames image for gift %s (%s)",
                        gift_id,
                        gift["name"],
                    )
                else:
                    uploaded += 1
                    logger.info(
                        "Uploaded BeetGames image for gift %s (%s)",
                        gift_id,
                        gift["name"],
                    )

            else:
                if generic_url is None:
                    generic_url = await _upload_generic_image()

                image_url = generic_url
                fallback += 1

                logger.info(
                    "Using generic TikTok image for gift %s (%s)",
                    gift_id,
                    gift["name"],
                )

            db_gift.image_url = image_url

        except (OSError, RuntimeError, R2StorageError) as exc:
            failed += 1

            logger.exception(
                "Failed to sync image for gift %s (%s)",
                gift_id,
                gift["name"],
            )

    await db.commit()

    summary_log = logger.warning if failed else logger.info

    summary_log(
        "Gift image sync complete: uploaded=%s, upgraded=%s, "
        "reused=%s, fallback=%s, failed=%s",
        uploaded,
        upgraded,
        reused,
        fallback,
        failed,
    )

    return {
        "uploaded": uploaded,
        "upgraded": upgraded,
        "reused": reused,
        "fallback": fallback,
        "failed": failed,
    }


async def _get_or_create_sync_state(db: AsyncSession) -> DBGiftCatalogSync:
    sync_state = await db.scalar(select(DBGiftCatalogSync).limit(1))

    if sync_state is None:
        sync_state = DBGiftCatalogSync(catalog_version=0)
        db.add(sync_state)

    return sync_state


async def _mark_attempt() -> None:
    async with AsyncSessionLocal() as db:
        sync_state = await _get_or_create_sync_state(db)
        sync_state.last_attempted_sync_at = datetime.now(timezone.utc)
        await db.commit()


async def _record_failure(exc: Exception) -> None:
    """Store the error on the sync row. Never raises."""

    try:
        async with AsyncSessionLocal() as db:
            sync_state = await _get_or_create_sync_state(db)
            sync_state.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            await db.commit()
    except Exception:
        logger.exception("Failed to record gift catalog sync failure")


async def _run_sync() -> dict[str, Any]:
    """
    The actual sync. Must only be called while holding the advisory lock.

    Euler is the source of truth for:

        ID
        name
        diamond count
        gift type

    BeetGames is only used for gift images.

    R2 stores the final stable image URLs.
    """

    # Fetch before opening a DB session so no connection or transaction
    # is held open during the network calls.
    gifts = await _fetch_euler_catalog()

    fingerprint = _fingerprint(gifts)

    async with AsyncSessionLocal() as db:
        try:
            sync_state = await _get_or_create_sync_state(db)

            # Abort before writing anything if the catalog looks truncated.
            # The gift_catalog_sync table has no count column, so compare
            # against the number of currently active gifts instead.
            previous_active = await db.scalar(
                select(func.count())
                .select_from(DBTikTokGift)
                .where(DBTikTokGift.is_active.is_(True))
            )

            _check_catalog_size(gifts, previous_active)

            # Upsert Euler metadata.
            existing_result = await db.execute(
                select(DBTikTokGift).where(
                    DBTikTokGift.tiktok_gift_id.in_([gift["id"] for gift in gifts])
                )
            )

            existing = {
                str(gift.tiktok_gift_id): gift
                for gift in existing_result.scalars().all()
            }

            incoming_ids = {gift["id"] for gift in gifts}

            now = datetime.now(timezone.utc)

            for gift in gifts:
                gift_id = gift["id"]

                db_gift = existing.get(gift_id)

                if db_gift is None:
                    db_gift = DBTikTokGift(
                        tiktok_gift_id=gift_id,
                        name=gift["name"],
                        diamond_count=gift["diamond_count"],
                        type=gift["type"],
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )

                    db.add(db_gift)

                else:
                    db_gift.name = gift["name"]
                    db_gift.diamond_count = gift["diamond_count"]
                    db_gift.type = gift["type"]
                    db_gift.is_active = True
                    db_gift.updated_at = now

            # Any gift that existed previously but no longer exists
            # in Euler becomes inactive.
            all_existing_result = await db.execute(select(DBTikTokGift))

            for db_gift in all_existing_result.scalars().all():
                if str(db_gift.tiktok_gift_id) not in incoming_ids:
                    db_gift.is_active = False

            # Record the successful metadata sync.
            if sync_state.catalog_hash != fingerprint:
                sync_state.catalog_version = (sync_state.catalog_version or 0) + 1
                sync_state.catalog_hash = fingerprint

            sync_state.last_successful_sync_at = now
            sync_state.last_successful_source = "euler"
            sync_state.last_error = None

            # Read now: ORM attributes may be expired after commit.
            catalog_version = sync_state.catalog_version

            # Commit metadata before starting image uploads.
            await db.commit()

            # Image sync is deliberately separate from Euler metadata.
            # A BeetGames/R2 image failure must not destroy the
            # authoritative Euler catalog update.
            image_stats = await _sync_gift_images(
                db,
                gifts,
            )

            logger.info(
                "Gift catalog sync completed successfully: %s gifts",
                len(gifts),
            )

            return {
                "status": "completed",
                "gifts": len(gifts),
                "catalog_version": catalog_version,
                "images": image_stats,
            }

        except Exception:
            await db.rollback()

            logger.exception("Gift catalog synchronization failed")

            raise


async def _try_acquire_lock():
    """
    Try to take the advisory lock on its own dedicated AUTOCOMMIT connection.
    Returns the open connection (caller must release it) or None if another
    sync already holds the lock. Never blocks.
    """

    lock_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    conn = await lock_engine.connect()

    acquired = await conn.scalar(
        text("SELECT pg_try_advisory_lock(hashtext(CAST(:name AS text)))"),
        {"name": GIFT_SYNC_LOCK_NAME},
    )

    if not acquired:
        await conn.close()
        return None

    return conn


async def _release_lock(lock_conn) -> None:
    try:
        await lock_conn.execute(
            text("SELECT pg_advisory_unlock(hashtext(CAST(:name AS text)))"),
            {"name": GIFT_SYNC_LOCK_NAME},
        )
    except Exception:
        logger.exception(
            "Failed to release gift sync advisory lock; "
            "invalidating the connection so Postgres drops it"
        )
        await lock_conn.invalidate()
    finally:
        await lock_conn.close()


# Keep strong references so fire-and-forget tasks aren't garbage collected
# mid-run (nothing else holds a reference to them once the route returns).
_background_sync_tasks: set[asyncio.Task] = set()


async def _run_sync_and_release(lock_conn) -> None:
    """
    Runs as a background task, e.g. from the manual sync route. Assumes the
    caller already acquired lock_conn via _try_acquire_lock(). Never raises:
    failures are recorded on the sync-state row instead, same as the
    scheduler does.
    """

    try:
        await _mark_attempt()
        await _run_sync()

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        await _record_failure(exc)

    finally:
        await _release_lock(lock_conn)


def start_gift_catalog_sync_task(lock_conn) -> asyncio.Task:
    """
    Spawn the sync as a background task and track it so it isn't GC'd.
    Caller (the route) must have already acquired lock_conn.
    """

    task = asyncio.create_task(_run_sync_and_release(lock_conn))
    _background_sync_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_sync_tasks.discard(t)
        logger.info("Gift catalog sync task finished")

    task.add_done_callback(_on_done)
    return task


async def sync_gift_catalog() -> dict[str, Any]:
    """
    Synchronize Euler's complete TikTok gift catalog, awaiting the full
    run (fetch + DB writes + image uploads) before returning. Used by the
    scheduler, where blocking is fine since nothing is waiting on an HTTP
    response.

    A PostgreSQL advisory lock stops two syncs running at once. The lock is
    held on its own dedicated AUTOCOMMIT connection, so it is not affected by
    the commits/rollbacks done by the work session (a session-level advisory
    lock belongs to one connection, and a normal AsyncSession can return its
    connection to the pool on every commit).

    If another sync already holds the lock, this run is skipped instead of
    blocking.
    """

    lock_conn = await _try_acquire_lock()

    if lock_conn is None:
        logger.warning("Gift catalog sync already running elsewhere, skipping")
        return {
            "status": "skipped",
            "reason": "Another gift catalog sync holds the advisory lock.",
        }

    try:
        await _mark_attempt()
        return await _run_sync()

    except Exception as exc:
        await _record_failure(exc)
        raise

    finally:
        await _release_lock(lock_conn)


async def gift_catalog_scheduler(
    stop_event: asyncio.Event,
    interval_seconds: int = 3600,
    retry_seconds: int = 300,
) -> None:
    """
    Periodically synchronize the gift catalog.

    After a failed run, retry after `retry_seconds` instead of waiting the
    full interval.
    """

    while not stop_event.is_set():
        wait_seconds = interval_seconds

        try:
            await sync_gift_catalog()

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception("Scheduled gift catalog sync failed")
            wait_seconds = retry_seconds

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=wait_seconds,
            )
        except asyncio.TimeoutError:
            pass