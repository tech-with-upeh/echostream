import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models import DBAudioAsset, DBMutedUser, DBUser, DBUserPreferences
from app.schemas import EventAlertPreferenceResponse, EventAlertPreferenceSchema, PreferencesSchema

router = APIRouter(tags=["Preferences"])
_ALLOWED_EVENT_TYPES = {"follow", "like", "gift"}

def _parse_list(value: str | None, default: list[str]) -> list[str]:
    if not value or not value.strip(): return default
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list): return [str(item) for item in parsed]
    except (json.JSONDecodeError, TypeError): pass
    return [item.strip() for item in value.split(",") if item.strip()] or default

def _parse_event_alerts(value: str | None) -> dict:
    if not value or not value.strip(): return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}

async def _get_or_create_preferences(current_user: DBUser, db: AsyncSession) -> DBUserPreferences:
    result = await db.execute(select(DBUserPreferences).where(DBUserPreferences.user_id == current_user.id))
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id); db.add(prefs); await db.commit(); await db.refresh(prefs)
    return prefs

def _serialize(prefs: DBUserPreferences) -> PreferencesSchema:
    return PreferencesSchema(
        tiktok_username=prefs.tiktok_username, tts_provider=prefs.tts_provider, voice=prefs.voice,
        fish_voice_id=prefs.fish_voice_id, fish_model=prefs.fish_model, pitch=prefs.pitch, volume=prefs.volume, speed=prefs.speed,
        emoji_to_words=prefs.emoji_to_words, filter_profanity=prefs.filter_profanity, require_command_prefix=prefs.require_command_prefix,
        max_message_length=prefs.max_message_length, comment_speech_enabled=prefs.comment_speech_enabled,
        comment_speech_template=prefs.comment_speech_template, event_speech_enabled=prefs.event_speech_enabled,
        event_speech_template=prefs.event_speech_template, event_alerts=_parse_event_alerts(prefs.event_alerts),
        gift_alert_enabled=prefs.gift_alert_enabled, gift_alert_type=prefs.gift_alert_type,
        gift_tts_template=prefs.gift_tts_template, gift_tts_voice=prefs.gift_tts_voice, gift_tts_provider=prefs.gift_tts_provider,
        gift_fish_voice_id=prefs.gift_fish_voice_id, gift_fish_model=prefs.gift_fish_model, gift_system_sound_id=prefs.gift_system_sound_id,
        gift_custom_audio_id=prefs.gift_custom_audio_id, gift_custom_audio_url=prefs.gift_custom_audio_url, gift_volume=prefs.gift_volume, gift_speed=prefs.gift_speed,
        allowed_user_types=_parse_list(prefs.allowed_user_types,["all"]), minimum_account_age_days=prefs.minimum_account_age_days,
        blocked_words=_parse_list(prefs.blocked_words,[]), spam_protection_enabled=prefs.spam_protection_enabled,
        block_repeated_words=prefs.block_repeated_words, auto_mute_repeat_offenders=prefs.auto_mute_repeat_offenders,
        spam_cooldown_seconds=prefs.spam_cooldown_seconds, spam_max_requests_per_minute=prefs.spam_max_requests_per_minute,
    )

def _validate_event_type(event_type: str) -> str:
    event_type = event_type.strip().lower()
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported event type. Allowed values: {', '.join(sorted(_ALLOWED_EVENT_TYPES))}.")
    return event_type

async def _validate_event_alert(payload: EventAlertPreferenceSchema, current_user: DBUser, db: AsyncSession) -> None:
    plan = current_user.plan.lower()
    if not payload.enabled: return
    if payload.alert_type == "tts":
        if not (payload.tts_template or "").strip():
            raise HTTPException(status_code=422, detail="TTS event alerts require a tts_template.")
        if payload.tts_provider == "fish" and plan != "pro":
            raise HTTPException(status_code=403, detail="Fish Audio event alerts are available on the Pro plan.")
        if payload.tts_provider == "fish" and not payload.fish_voice_id:
            raise HTTPException(status_code=422, detail="Fish event alerts require fish_voice_id.")
    elif payload.alert_type == "system_sound":
        if not payload.system_sound_id:
            raise HTTPException(status_code=422, detail="System sound event alerts require system_sound_id.")
    elif payload.alert_type == "custom_audio":
        if plan not in {"essential", "pro"}:
            raise HTTPException(status_code=403, detail="Custom audio is available on the Essential and Pro plans.")
        if not payload.custom_audio_id and not payload.custom_audio_url:
            raise HTTPException(status_code=422, detail="Custom audio event alerts require custom_audio_id.")
        if payload.custom_audio_id:
            result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.id == payload.custom_audio_id, DBAudioAsset.owner_user_id == current_user.id))
            if result.scalar_one_or_none() is None:
                raise HTTPException(status_code=403, detail="Custom audio must belong to the current user.")
        elif payload.custom_audio_url:
            result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.public_url == payload.custom_audio_url, DBAudioAsset.owner_user_id == current_user.id))
            if result.scalar_one_or_none() is None:
                raise HTTPException(status_code=403, detail="Custom audio must belong to the current user.")

@router.get("/v1/preferences", response_model=PreferencesSchema)
async def get_preferences(current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    return _serialize(await _get_or_create_preferences(current_user,db))

@router.put("/v1/preferences", response_model=PreferencesSchema)
async def update_preferences(payload: PreferencesSchema,current_user: DBUser=Depends(get_current_user),db: AsyncSession=Depends(get_db)):
    prefs=await _get_or_create_preferences(current_user,db); plan=current_user.plan.lower(); is_pro=plan=="pro"
    if payload.tts_provider=="fish" and not is_pro: raise HTTPException(403,"Fish Audio is available on the Pro plan.")
    if not is_pro and any([payload.emoji_to_words,payload.filter_profanity,payload.require_command_prefix,payload.minimum_account_age_days!=1,bool(payload.blocked_words),payload.spam_protection_enabled,not payload.block_repeated_words,payload.auto_mute_repeat_offenders,payload.spam_cooldown_seconds!=2,payload.spam_max_requests_per_minute!=10]): raise HTTPException(403,"These advanced TTS and spam-protection settings are available on the Pro plan.")
    if payload.gift_alert_type=="tts" and payload.gift_tts_provider=="fish" and not is_pro: raise HTTPException(403,"Fish Audio gift alerts are available on the Pro plan.")
    asset=None
    if payload.gift_custom_audio_id:
        if plan not in {"essential","pro"}: raise HTTPException(403,"Custom audio is available on the Essential and Pro plans.")
        asset=(await db.execute(select(DBAudioAsset).where(DBAudioAsset.id==payload.gift_custom_audio_id,DBAudioAsset.owner_user_id==current_user.id))).scalar_one_or_none()
        if asset is None: raise HTTPException(403,"Custom audio must belong to the current user.")
    elif payload.gift_custom_audio_url:
        if plan not in {"essential","pro"}: raise HTTPException(403,"Custom audio is available on the Essential and Pro plans.")
        asset=(await db.execute(select(DBAudioAsset).where(DBAudioAsset.public_url==payload.gift_custom_audio_url,DBAudioAsset.owner_user_id==current_user.id))).scalar_one_or_none()
        if asset is None: raise HTTPException(403,"Custom audio must belong to the current user.")
    fields=["tiktok_username","tts_provider","voice","fish_voice_id","fish_model","pitch","volume","speed","emoji_to_words","filter_profanity","require_command_prefix","max_message_length","comment_speech_enabled","comment_speech_template","event_speech_enabled","event_speech_template","gift_alert_enabled","gift_alert_type","gift_tts_template","gift_tts_voice","gift_tts_provider","gift_fish_voice_id","gift_fish_model","gift_system_sound_id","gift_custom_audio_id","gift_volume","gift_speed","minimum_account_age_days","spam_protection_enabled","block_repeated_words","auto_mute_repeat_offenders","spam_cooldown_seconds","spam_max_requests_per_minute"]
    for field in fields: setattr(prefs,field,getattr(payload,field))
    prefs.gift_custom_audio_url=asset.public_url if asset else payload.gift_custom_audio_url
    prefs.event_alerts=json.dumps({key: value.model_dump() for key, value in payload.event_alerts.items()})
    prefs.allowed_user_types=json.dumps(payload.allowed_user_types); prefs.blocked_words=json.dumps(payload.blocked_words)
    await db.commit(); await db.refresh(prefs); return _serialize(prefs)

@router.get("/v1/preferences/events", response_model=list[EventAlertPreferenceResponse])
async def list_event_alert_preferences(current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    prefs = await _get_or_create_preferences(current_user, db)
    configured = _parse_event_alerts(prefs.event_alerts)
    return [EventAlertPreferenceResponse(event_type=event, **value) for event, value in configured.items() if event in _ALLOWED_EVENT_TYPES]

@router.get("/v1/preferences/events/{event_type}", response_model=EventAlertPreferenceResponse)
async def get_event_alert_preference(event_type: str, current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    event_type = _validate_event_type(event_type)
    prefs = await _get_or_create_preferences(current_user, db)
    configured = _parse_event_alerts(prefs.event_alerts)
    value = configured.get(event_type)
    if value is None:
        value = EventAlertPreferenceSchema(tts_template=f"{{{{user}}}} {event_type}").model_dump()
    return EventAlertPreferenceResponse(event_type=event_type, **value)

@router.put("/v1/preferences/events/{event_type}", response_model=EventAlertPreferenceResponse)
async def upsert_event_alert_preference(event_type: str, payload: EventAlertPreferenceSchema, current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    event_type = _validate_event_type(event_type)
    await _validate_event_alert(payload, current_user, db)
    prefs = await _get_or_create_preferences(current_user, db)
    configured = _parse_event_alerts(prefs.event_alerts)
    data = payload.model_dump()
    if data.get("custom_audio_id"):
        asset = (await db.execute(select(DBAudioAsset).where(DBAudioAsset.id == data["custom_audio_id"], DBAudioAsset.owner_user_id == current_user.id))).scalar_one_or_none()
        data["custom_audio_url"] = asset.public_url
    configured[event_type] = data
    prefs.event_alerts = json.dumps(configured)
    await db.commit(); await db.refresh(prefs)
    return EventAlertPreferenceResponse(event_type=event_type, **data)

@router.delete("/v1/preferences/events/{event_type}")
async def delete_event_alert_preference(event_type: str, current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    event_type = _validate_event_type(event_type)
    prefs = await _get_or_create_preferences(current_user, db)
    configured = _parse_event_alerts(prefs.event_alerts)
    if event_type not in configured:
        raise HTTPException(status_code=404, detail="Event alert preference not found.")
    configured.pop(event_type)
    prefs.event_alerts = json.dumps(configured)
    await db.commit()
    return {"message": f"{event_type} alert preference removed."}

@router.get("/v1/muted-users")
async def list_muted_users(current_user: DBUser=Depends(get_current_user),db: AsyncSession=Depends(get_db)):
    result=await db.execute(select(DBMutedUser).where(DBMutedUser.owner_id==current_user.id).order_by(DBMutedUser.created_at.desc())); return result.scalars().all()

@router.post("/v1/muted-users")
async def mute_user(payload:dict,current_user:DBUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    username=str(payload.get("tiktok_username","")).strip()
    if not username: raise HTTPException(400,"tiktok_username is required.")
    item=DBMutedUser(owner_id=current_user.id,tiktok_user_id=payload.get("tiktok_user_id"),tiktok_username=username,reason=str(payload.get("reason","manual")),created_at=datetime.now(timezone.utc).replace(tzinfo=None)); db.add(item); await db.commit(); await db.refresh(item); return item

@router.delete("/v1/muted-users/{muted_id}")
async def unmute_user(muted_id:int,current_user:DBUser=Depends(get_current_user),db:AsyncSession=Depends(get_db)):
    item=(await db.execute(select(DBMutedUser).where(DBMutedUser.id==muted_id,DBMutedUser.owner_id==current_user.id))).scalar_one_or_none()
    if item is None: raise HTTPException(404,"Muted user not found.")
    await db.delete(item); await db.commit(); return {"message":"User unmuted successfully."}
