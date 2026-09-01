import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DBGiftCatalogSync, DBTikTokGift

logger = logging.getLogger(__name__)
_LOCK_KEY = 84639217
_CATALOG_PATH = "/webcast/gifts/catalog"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _image_url(item: dict[str, Any]) -> str | None:
    value = _value(item, "image_url", "imageUrl", "icon_url", "iconUrl")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _value(value, "url", "uri", "src")
    return None


def _extract_gifts(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None, int | None]:
    gifts = payload.get("gifts")
    if gifts is None and isinstance(payload.get("data"), dict):
        gifts = payload["data"].get("gifts")
    if gifts is None and isinstance(payload.get("result"), dict):
        gifts = payload["result"].get("gifts")
    if not isinstance(gifts, list):
        raise ValueError("Euler gift catalog response did not contain a gifts array")

    total_pages = _value(payload, "totalPages", "total_pages")
    page_size = _value(payload, "pageSize", "page_size")
    if isinstance(payload.get("data"), dict):
        total_pages = total_pages or _value(payload["data"], "totalPages", "total_pages")
        page_size = page_size or _value(payload["data"], "pageSize", "page_size")
    return [g for g in gifts if isinstance(g, dict)], _as_int(total_pages), _as_int(page_size)


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    gift_id = _value(raw, "id", "gift_id", "giftId")
    name = _value(raw, "name", "gift_name", "giftName")
    if gift_id is None or name is None:
        raise ValueError("Euler returned a gift without id or name")
    return {
        "tiktok_gift_id": str(gift_id),
        "name": str(name),
        "diamond_count": _as_int(_value(raw, "diamond_count", "diamondCount", "diamond_count_value")),
        "type": _as_int(_value(raw, "type", "gift_type", "giftType")),
        "image_url": _image_url(raw),
    }


def _fingerprint(gifts: list[dict[str, Any]]) -> str:
    canonical = json.dumps(sorted(gifts, key=lambda x: x["tiktok_gift_id"]), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _fetch_euler_catalog() -> list[dict[str, Any]]:
    if not settings.EULER_STREAM_API_KEY:
        raise RuntimeError("EULER_STREAM_API_KEY is not configured")

    base = settings.EULER_STREAM_BASE_URL.rstrip("/")
    timeout = httpx.Timeout(30.0, connect=10.0)
    all_gifts: list[dict[str, Any]] = []
    page = 1
    page_size = 100

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            response = await client.get(
                f"{base}{_CATALOG_PATH}",
                params={"pageSize": page_size, "pageNumber": page},
                headers={"Accept": "application/json", "x-api-key": settings.EULER_STREAM_API_KEY},
            )
            response.raise_for_status()
            payload = response.json()
            raw_gifts, total_pages, returned_page_size = _extract_gifts(payload)
            all_gifts.extend(_normalize(gift) for gift in raw_gifts)

            if not raw_gifts:
                break
            if total_pages is not None:
                if page >= total_pages:
                    break
            elif len(raw_gifts) < (returned_page_size or page_size):
                break
            page += 1
            if page > 1000:
                raise RuntimeError("Euler gift catalog pagination exceeded safety limit")

    deduped = {gift["tiktok_gift_id"]: gift for gift in all_gifts}
    if not deduped:
        raise RuntimeError("Euler returned an empty gift catalog; refusing to replace the existing catalog")
    return list(deduped.values())


async def sync_gift_catalog() -> dict[str, Any]:
    """Fetch the complete Euler catalog and apply it atomically."""
    async with AsyncSessionLocal() as db:
        acquired = (await db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY})).scalar_one()
        if not acquired:
            return {"status": "already_running"}

        now = _utcnow()
        try:
            meta = (await db.execute(select(DBGiftCatalogSync).where(DBGiftCatalogSync.id == 1))).scalar_one_or_none()
            if meta is None:
                meta = DBGiftCatalogSync(id=1, catalog_version=0)
                db.add(meta)
                await db.flush()
            meta.last_attempted_sync_at = now
            meta.last_error = None
            await db.commit()

            try:
                gifts = await _fetch_euler_catalog()
            except Exception as exc:
                async with AsyncSessionLocal() as status_db:
                    status = (await status_db.execute(select(DBGiftCatalogSync).where(DBGiftCatalogSync.id == 1))).scalar_one_or_none()
                    if status is None:
                        status = DBGiftCatalogSync(id=1, catalog_version=0)
                        status_db.add(status)
                    status.last_attempted_sync_at = now
                    status.last_error = f"{type(exc).__name__}: {exc}"
                    await status_db.commit()
                logger.exception("TikTok gift catalog sync failed")
                return {"status": "failed", "error": str(exc)}

            catalog_hash = _fingerprint(gifts)
            meta = (await db.execute(select(DBGiftCatalogSync).where(DBGiftCatalogSync.id == 1))).scalar_one()
            changed = meta.catalog_hash != catalog_hash

            # No catalog rows are changed until every page has been fetched and validated.
            for gift in gifts:
                stmt = insert(DBTikTokGift).values(**gift, is_active=True, created_at=now, updated_at=now).on_conflict_do_update(
                    index_elements=[DBTikTokGift.tiktok_gift_id],
                    set_={
                        "name": gift["name"], "diamond_count": gift["diamond_count"], "type": gift["type"],
                        "image_url": gift["image_url"], "is_active": True, "updated_at": now,
                    },
                )
                await db.execute(stmt)

            incoming_ids = [gift["tiktok_gift_id"] for gift in gifts]
            await db.execute(
                update(DBTikTokGift)
                .where(~DBTikTokGift.tiktok_gift_id.in_(incoming_ids))
                .values(is_active=False, updated_at=now)
            )

            meta.last_successful_sync_at = now
            meta.last_successful_source = "euler"
            meta.last_error = None
            meta.catalog_hash = catalog_hash
            if changed:
                meta.catalog_version = int(meta.catalog_version or 0) + 1
            await db.commit()
            return {"status": "success", "count": len(gifts), "changed": changed, "version": meta.catalog_version}
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})
            await db.commit()


async def gift_catalog_scheduler() -> None:
    interval = max(1, settings.GIFT_CATALOG_SYNC_INTERVAL_HOURS) * 3600
    while True:
        try:
            async with AsyncSessionLocal() as db:
                exists = (await db.execute(select(DBTikTokGift.id).limit(1))).first()
            if exists is None:
                await sync_gift_catalog()
            else:
                async with AsyncSessionLocal() as db:
                    meta = (await db.execute(select(DBGiftCatalogSync).where(DBGiftCatalogSync.id == 1))).scalar_one_or_none()
                last = meta.last_successful_sync_at if meta else None
                if last is None or last <= _utcnow() - timedelta(seconds=interval):
                    await sync_gift_catalog()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Gift catalog scheduler iteration failed")
        await asyncio.sleep(interval)
