import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import DBGiftPreference, DBUser
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


def _serialize_gifts(raw) -> list[TikTokGiftSchema]:
    if not raw:
        return []
    values = raw.values() if isinstance(raw, dict) else raw
    result = []
    for gift in values:
        gift_id = getattr(gift, "id", None) or getattr(gift, "gift_id", None)
        name = getattr(gift, "name", None) or getattr(gift, "gift_name", None)
        if gift_id is None or name is None:
            continue
        image = getattr(gift, "image", None)
        image_url = getattr(image, "url", None) if image is not None else None
        result.append(TikTokGiftSchema(
            id=str(gift_id), name=str(name),
            diamond_count=getattr(gift, "diamond_count", None),
            type=getattr(gift, "type", None), image_url=image_url,
        ))
    result.sort(key=lambda item: item.name.lower())
    return result


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
def list_gift_preferences(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(DBGiftPreference).filter(DBGiftPreference.owner_id == current_user.id).order_by(DBGiftPreference.gift_name.asc()).all()
    return [_gift_to_schema(item) for item in items]


@router.put("/v1/gift-preferences/{gift_id}", response_model=GiftPreferenceResponse)
def upsert_gift_preference(gift_id: str, payload: GiftAlertPreferenceSchema, current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Gift-specific alert settings are available on the Pro plan.")
    if payload.alert_type == "tts" and payload.tts_provider == "fish" and current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Fish Audio gift alerts are available on the Pro plan.")
    item = db.query(DBGiftPreference).filter(DBGiftPreference.owner_id == current_user.id, DBGiftPreference.gift_id == gift_id).first()
    if item is None:
        item = DBGiftPreference(owner_id=current_user.id, gift_id=gift_id, gift_name=gift_id)
        db.add(item)
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    db.commit(); db.refresh(item)
    return _gift_to_schema(item)


@router.delete("/v1/gift-preferences/{gift_id}")
def delete_gift_preference(gift_id: str, current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Gift-specific alert settings are available on the Pro plan.")
    item = db.query(DBGiftPreference).filter(DBGiftPreference.owner_id == current_user.id, DBGiftPreference.gift_id == gift_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Gift preference not found.")
    db.delete(item); db.commit()
    return {"message": "Gift-specific preference removed."}


@router.post("/v1/gift-alerts/custom-audio")
async def upload_gift_custom_audio(file: UploadFile = File(...), current_user: DBUser = Depends(get_current_user)):
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Custom gift audio is available on the Pro plan.")
    allowed = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/webm"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported audio format. Use MP3, WAV, OGG, or WebM audio.")
    upload_dir = Path("uploads/gift-alerts")
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "audio").suffix.lower() or ".audio"
    filename = f"{current_user.id}-{uuid.uuid4().hex}{suffix}"
    path = upload_dir / filename
    size = 0
    with path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 10 * 1024 * 1024:
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Audio file must be 10 MB or smaller.")
            output.write(chunk)
    return {"url": f"/uploads/gift-alerts/{filename}", "filename": filename, "size": size}
