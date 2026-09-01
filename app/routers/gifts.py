from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db, require_admin
from app.gift_catalog import sync_gift_catalog
from app.models import DBAudioAsset, DBGiftCatalogSync, DBGiftPreference, DBTikTokGift, DBUser
from app.r2_storage import R2StorageError, delete_gift_audio, upload_audio
from app.schemas import GiftAlertPreferenceSchema, GiftPreferenceResponse, TikTokGiftSchema

router = APIRouter(tags=["TikTok Gifts"])


def _gift_to_schema(item: DBGiftPreference) -> GiftPreferenceResponse:
    return GiftPreferenceResponse(id=item.id, gift_id=item.gift_id, gift_name=item.gift_name, enabled=item.enabled, alert_type=item.alert_type, tts_template=item.tts_template, tts_provider=item.tts_provider, voice=item.voice, fish_voice_id=item.fish_voice_id, fish_model=item.fish_model, system_sound_id=item.system_sound_id, custom_audio_id=item.custom_audio_id, custom_audio_url=item.custom_audio_url, volume=item.volume, speed=item.speed, pitch=item.pitch)


def _is_owned_gift_audio_url(url: str | None, user_id: int) -> bool:
    if not url:
        return False
    expected = urlparse(settings.R2_PUBLIC_BASE_URL.rstrip("/"))
    parsed = urlparse(url)
    return parsed.scheme == expected.scheme and parsed.netloc == expected.netloc and parsed.path.lstrip("/").startswith(f"user-sounds/{user_id}/")


def _validate_alert_payload(payload: GiftAlertPreferenceSchema, user_id: int, plan: str) -> None:
    if not payload.enabled:
        return
    if payload.alert_type == "tts":
        if not (payload.tts_template or "").strip():
            raise HTTPException(status_code=422, detail="TTS gift alerts require a tts_template.")
        if payload.tts_provider == "fish" and plan.lower() != "pro":
            raise HTTPException(status_code=403, detail="Fish Audio gift alerts are available on the Pro plan.")
        if payload.tts_provider == "fish" and not payload.fish_voice_id:
            raise HTTPException(status_code=422, detail="Fish gift alerts require fish_voice_id.")
    elif payload.alert_type == "system_sound":
        if not payload.system_sound_id:
            raise HTTPException(status_code=422, detail="System sound gift alerts require system_sound_id.")
    elif payload.alert_type == "custom_audio":
        if plan.lower() not in {"essential", "pro"}:
            raise HTTPException(status_code=403, detail="Custom audio is available on the Essential and Pro plans.")
        if not payload.custom_audio_id and not payload.custom_audio_url:
            raise HTTPException(status_code=422, detail="Custom audio gift alerts require custom_audio_id.")
        if payload.custom_audio_url and not _is_owned_gift_audio_url(payload.custom_audio_url, user_id):
            raise HTTPException(status_code=403, detail="Custom audio must belong to the current user.")


@router.get("/v1/gifts", response_model=list[TikTokGiftSchema])
async def list_tiktok_gifts(request: Request, response: Response, db: AsyncSession = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    meta = (await db.execute(select(DBGiftCatalogSync).where(DBGiftCatalogSync.id == 1))).scalar_one_or_none()
    version = int(meta.catalog_version) if meta else 0
    etag = f'"gift-catalog-v{version}"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=300, must-revalidate"
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, max-age=300, must-revalidate"})
    result = await db.execute(select(DBTikTokGift).where(DBTikTokGift.is_active.is_(True)).order_by(DBTikTokGift.name.asc()))
    return [TikTokGiftSchema(id=item.tiktok_gift_id, name=item.name, diamond_count=item.diamond_count, type=item.type, image_url=item.image_url) for item in result.scalars().all()]


@router.get("/v1/tiktok/gifts", response_model=list[TikTokGiftSchema], include_in_schema=False)
async def list_tiktok_gifts_legacy(db: AsyncSession = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    result = await db.execute(select(DBTikTokGift).where(DBTikTokGift.is_active.is_(True)).order_by(DBTikTokGift.name.asc()))
    return [TikTokGiftSchema(id=item.tiktok_gift_id, name=item.name, diamond_count=item.diamond_count, type=item.type, image_url=item.image_url) for item in result.scalars().all()]


@router.get("/v1/gifts/sync-status")
async def gift_catalog_sync_status(current_user: DBUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    meta = (await db.execute(select(DBGiftCatalogSync).where(DBGiftCatalogSync.id == 1))).scalar_one_or_none()
    if meta is None:
        return {"status": "never_synced", "stale": True, "catalog_version": 0}
    now = datetime.now(timezone.utc)
    last = meta.last_successful_sync_at
    stale = True
    if last is not None:
        last_aware = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
        stale = (now - last_aware).total_seconds() > settings.GIFT_CATALOG_STALE_AFTER_HOURS * 3600
    return {"status": "stale" if stale else "healthy", "stale": stale, "catalog_version": meta.catalog_version, "last_attempted_sync_at": meta.last_attempted_sync_at, "last_successful_sync_at": meta.last_successful_sync_at, "last_successful_source": meta.last_successful_source, "last_error": meta.last_error}


@router.post("/v1/admin/gifts/sync")
async def manual_gift_catalog_sync(current_user: DBUser = Depends(require_admin)):
    return await sync_gift_catalog()


@router.get("/v1/gift-preferences", response_model=list[GiftPreferenceResponse])
async def list_gift_preferences(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBGiftPreference).where(DBGiftPreference.owner_id == current_user.id).order_by(DBGiftPreference.gift_name.asc()))
    return [_gift_to_schema(item) for item in result.scalars().all()]


@router.put("/v1/gift-preferences/{gift_id}")
async def upsert_gift_preference(gift_id: str, payload: GiftAlertPreferenceSchema, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Gift-specific alert settings are available on the Pro plan.")
    _validate_alert_payload(payload, current_user.id, current_user.plan)
    gift_result = await db.execute(select(DBTikTokGift).where(DBTikTokGift.tiktok_gift_id == gift_id))
    gift = gift_result.scalar_one_or_none()
    if gift is None:
        raise HTTPException(status_code=404, detail="TikTok gift not found in the local catalog.")
    result = await db.execute(select(DBGiftPreference).where(DBGiftPreference.owner_id == current_user.id, DBGiftPreference.gift_id == gift_id))
    item = result.scalar_one_or_none()
    old_audio_url = item.custom_audio_url if item else None
    if item is None:
        item = DBGiftPreference(owner_id=current_user.id, gift_id=gift_id, gift_name=gift.name)
        db.add(item)
    else:
        item.gift_name = gift.name
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    if payload.custom_audio_id:
        asset_result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.id == payload.custom_audio_id, DBAudioAsset.owner_user_id == current_user.id))
        asset = asset_result.scalar_one_or_none()
        if asset is None:
            raise HTTPException(status_code=403, detail="Custom audio must belong to the current user.")
        item.custom_audio_url = asset.public_url
    await db.commit()
    await db.refresh(item)
    if old_audio_url and old_audio_url != item.custom_audio_url:
        try:
            await delete_gift_audio(old_audio_url)
        except R2StorageError:
            pass
    return _gift_to_schema(item)


@router.delete("/v1/gift-preferences/{gift_id}")
async def delete_gift_preference(gift_id: str, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Gift-specific alert settings are available on the Pro plan.")
    result = await db.execute(select(DBGiftPreference).where(DBGiftPreference.owner_id == current_user.id, DBGiftPreference.gift_id == gift_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Gift preference not found.")
    old_audio_url = item.custom_audio_url
    await db.delete(item)
    await db.commit()
    if old_audio_url:
        try:
            await delete_gift_audio(old_audio_url)
        except R2StorageError:
            pass
    return {"message": "Gift-specific preference removed."}


@router.post("/v1/gift-alerts/custom-audio")
async def upload_gift_custom_audio(file: UploadFile = File(...), current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.plan.lower() not in {"essential", "pro"}:
        raise HTTPException(status_code=403, detail="Custom audio is available on the Essential and Pro plans.")
    contents = await file.read()
    await file.close()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file must be 10 MB or smaller.")
    name = Path(file.filename or "custom-audio").stem.strip() or "custom-audio"
    try:
        key, url = await upload_audio(contents, owner_user_id=current_user.id, name=name)
    except R2StorageError as exc:
        status_code = 400 if str(exc).startswith("Unsupported audio format") or str(exc) == "Audio file is empty." else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)
    asset = DBAudioAsset(name=name[:255], r2_key=key, public_url=url, owner_user_id=current_user.id, created_at=now, updated_at=now)
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return {"id": asset.id, "name": asset.name, "url": asset.public_url, "size": len(contents)}
