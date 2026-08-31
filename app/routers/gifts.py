from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models import DBGiftPreference, DBUser
from app.r2_storage import R2StorageError, delete_gift_audio, upload_gift_audio
from app.schemas import GiftAlertPreferenceSchema, GiftPreferenceResponse, TikTokGiftSchema
from app.tiktok_manager import active_tiktok_clients

router = APIRouter(tags=["TikTok Gifts"])


def _gift_to_schema(item: DBGiftPreference) -> GiftPreferenceResponse:
    return GiftPreferenceResponse(
        id=item.id, gift_id=item.gift_id, gift_name=item.gift_name, enabled=item.enabled,
        alert_type=item.alert_type, tts_template=item.tts_template, tts_provider=item.tts_provider,
        voice=item.voice, fish_voice_id=item.fish_voice_id, fish_model=item.fish_model,
        system_sound_id=item.system_sound_id, custom_audio_url=item.custom_audio_url,
        volume=item.volume, speed=item.speed, pitch=item.pitch,
    )


def _get_field(value, *names):
    if isinstance(value, dict):
        for name in names:
            if value.get(name) is not None:
                return value[name]
    for name in names:
        result = getattr(value, name, None)
        if result is not None:
            return result
    return None


def _serialize_gifts(raw) -> list[TikTokGiftSchema]:
    if not raw:
        return []
    values = raw.values() if isinstance(raw, dict) else raw
    result = []
    for gift in values:
        gift_id = _get_field(gift, "id", "gift_id")
        name = _get_field(gift, "name", "gift_name")
        if gift_id is None or name is None:
            continue
        image = _get_field(gift, "image")
        image_url = _get_field(image, "url") if image is not None else _get_field(gift, "image_url")
        result.append(TikTokGiftSchema(id=str(gift_id), name=str(name), diamond_count=_get_field(gift, "diamond_count", "diamondCount"), type=_get_field(gift, "type"), image_url=image_url))
    result.sort(key=lambda item: item.name.lower())
    return result


def _find_live_gift(user_id: int, gift_id: str):
    client = active_tiktok_clients.get(user_id)
    if client is None:
        return None
    gifts = _serialize_gifts(getattr(client, "gift_info", None))
    return next((gift for gift in gifts if gift.id == gift_id), None)


def _is_owned_gift_audio_url(url: str | None, user_id: int) -> bool:
    if not url:
        return False
    expected = urlparse(settings.R2_PUBLIC_BASE_URL.rstrip("/"))
    parsed = urlparse(url)
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        return False
    return parsed.path.lstrip("/").startswith(f"gift-alerts/{user_id}-")


def _validate_alert_payload(payload: GiftAlertPreferenceSchema, user_id: int) -> None:
    if not payload.enabled:
        return
    if payload.alert_type == "tts":
        if not (payload.tts_template or "").strip():
            raise HTTPException(status_code=422, detail="TTS gift alerts require a tts_template.")
        if payload.tts_provider == "fish" and not payload.fish_voice_id:
            raise HTTPException(status_code=422, detail="Fish gift alerts require fish_voice_id.")
    elif payload.alert_type == "system_sound":
        if not payload.system_sound_id:
            raise HTTPException(status_code=422, detail="System sound gift alerts require system_sound_id.")
    elif payload.alert_type == "custom_audio":
        if not payload.custom_audio_url:
            raise HTTPException(status_code=422, detail="Custom audio gift alerts require custom_audio_url.")
        if not _is_owned_gift_audio_url(payload.custom_audio_url, user_id):
            raise HTTPException(status_code=403, detail="Custom audio must belong to the current user.")


@router.get("/v1/tiktok/gifts", response_model=list[TikTokGiftSchema])
def list_tiktok_gifts(current_user: DBUser = Depends(get_current_user)):
    client = active_tiktok_clients.get(current_user.id)
    if client is None:
        raise HTTPException(status_code=409, detail="Start a TikTok live session first so the available gifts can be loaded.")
    gifts = getattr(client, "gift_info", None)
    if not gifts:
        raise HTTPException(status_code=503, detail="TikTok gift information is not available yet. Try again shortly.")
    return _serialize_gifts(gifts)


@router.get("/v1/gift-preferences", response_model=list[GiftPreferenceResponse])
async def list_gift_preferences(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBGiftPreference).where(DBGiftPreference.owner_id == current_user.id).order_by(DBGiftPreference.gift_name.asc()))
    return [_gift_to_schema(item) for item in result.scalars().all()]


@router.put("/v1/gift-preferences/{gift_id}")
async def upsert_gift_preference(gift_id: str, payload: GiftAlertPreferenceSchema, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Gift-specific alert settings are available on the Pro plan.")
    _validate_alert_payload(payload, current_user.id)
    result = await db.execute(select(DBGiftPreference).where(DBGiftPreference.owner_id == current_user.id, DBGiftPreference.gift_id == gift_id))
    item = result.scalar_one_or_none()
    live_gift = _find_live_gift(current_user.id, gift_id)
    gift_name = live_gift.name if live_gift is not None else gift_id
    old_audio_url = item.custom_audio_url if item is not None else None
    if item is None:
        item = DBGiftPreference(owner_id=current_user.id, gift_id=gift_id, gift_name=gift_name)
        db.add(item)
    elif live_gift is not None:
        item.gift_name = gift_name
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
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
async def upload_gift_custom_audio(file: UploadFile = File(...), current_user: DBUser = Depends(get_current_user)):
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Custom gift audio is available on the Pro plan.")
    contents = await file.read()
    await file.close()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file must be 10 MB or smaller.")
    try:
        url = await upload_gift_audio(contents, current_user.id)
    except R2StorageError as exc:
        status_code = 400 if str(exc).startswith("Unsupported audio format") or str(exc) == "Audio file is empty." else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"url": url, "size": len(contents)}
