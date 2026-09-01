import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_current_user, get_db
from app.models import DBAudioAsset, DBMutedUser, DBUser, DBUserPreferences
from app.schemas import PreferencesSchema, EventAlertPreferenceSchema

router = APIRouter(tags=["Preferences"])
_ALLOWED_EVENT_TYPES = {"follow", "like", "gift"}

def _parse_list(value, default):
    try:
        parsed = json.loads(value) if value else default
        return parsed if isinstance(parsed, list) else default
    except (TypeError, json.JSONDecodeError): return default

def _parse_events(value):
    try:
        parsed = json.loads(value) if value else {}
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError): return {}

async def _get_or_create_preferences(current_user, db):
    prefs = (await db.execute(select(DBUserPreferences).where(DBUserPreferences.user_id == current_user.id))).scalar_one_or_none()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id)
        db.add(prefs); await db.commit(); await db.refresh(prefs)
    return prefs

async def _validate_event(event_type, payload, current_user, db):
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise HTTPException(422, f"Unsupported event type: {event_type}")
    if not payload.enabled: return None
    plan = current_user.plan.lower()
    if payload.alert_type == "tts":
        if not (payload.tts_template or "").strip(): raise HTTPException(422, "TTS event alerts require a tts_template.")
        if payload.tts_provider == "fish" and plan != "pro": raise HTTPException(403, "Fish Audio event alerts are available on the Pro plan.")
        if payload.tts_provider == "fish" and not payload.fish_voice_id: raise HTTPException(422, "Fish event alerts require fish_voice_id.")
    elif payload.alert_type == "system_sound":
        if not payload.system_sound_id: raise HTTPException(422, "System sound event alerts require system_sound_id.")
    elif payload.alert_type == "custom_audio":
        if plan not in {"essential", "pro"}: raise HTTPException(403, "Custom audio is available on the Essential and Pro plans.")
        if not payload.custom_audio_id and not payload.custom_audio_url: raise HTTPException(422, "Custom audio event alerts require custom_audio_id.")
        if payload.custom_audio_id:
            asset = (await db.execute(select(DBAudioAsset).where(DBAudioAsset.id == payload.custom_audio_id, DBAudioAsset.owner_user_id == current_user.id))).scalar_one_or_none()
            if asset is None: raise HTTPException(403, "Custom audio must belong to the current user.")
            return asset
    return None

async def _normalise_events(events, current_user, db):
    if any(event not in _ALLOWED_EVENT_TYPES for event in events):
        raise HTTPException(422, "Unsupported event type in events.")
    result = {}
    for event_type, payload in events.items():
        asset = await _validate_event(event_type, payload, current_user, db)
        data = payload.model_dump()
        if asset is not None: data["custom_audio_url"] = asset.public_url
        result[event_type] = data
    return result

def _serialize(prefs):
    return PreferencesSchema(
        tiktok_username=prefs.tiktok_username, tts_provider=prefs.tts_provider, voice=prefs.voice, fish_voice_id=prefs.fish_voice_id,
        fish_model=prefs.fish_model, pitch=prefs.pitch, volume=prefs.volume, speed=prefs.speed, emoji_to_words=prefs.emoji_to_words,
        filter_profanity=prefs.filter_profanity, require_command_prefix=prefs.require_command_prefix, max_message_length=prefs.max_message_length,
        comment_speech_enabled=prefs.comment_speech_enabled, comment_speech_template=prefs.comment_speech_template,
        events=_parse_events(prefs.event_alerts), allowed_user_types=_parse_list(prefs.allowed_user_types, ["all"]),
        minimum_account_age_days=prefs.minimum_account_age_days, blocked_words=_parse_list(prefs.blocked_words, []),
        spam_protection_enabled=prefs.spam_protection_enabled, block_repeated_words=prefs.block_repeated_words,
        auto_mute_repeat_offenders=prefs.auto_mute_repeat_offenders, spam_cooldown_seconds=prefs.spam_cooldown_seconds,
        spam_max_requests_per_minute=prefs.spam_max_requests_per_minute,
    )

@router.get("/v1/preferences", response_model=PreferencesSchema)
async def get_preferences(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _serialize(await _get_or_create_preferences(current_user, db))

@router.put("/v1/preferences", response_model=PreferencesSchema)
async def update_preferences(payload: PreferencesSchema, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    prefs = await _get_or_create_preferences(current_user, db)
    plan = current_user.plan.lower(); is_pro = plan == "pro"
    if payload.tts_provider == "fish" and not is_pro: raise HTTPException(403, "Fish Audio is available on the Pro plan.")
    if not is_pro and any([payload.emoji_to_words, payload.filter_profanity, payload.require_command_prefix, payload.minimum_account_age_days != 1, bool(payload.blocked_words), payload.spam_protection_enabled, not payload.block_repeated_words, payload.auto_mute_repeat_offenders, payload.spam_cooldown_seconds != 2, payload.spam_max_requests_per_minute != 10]): raise HTTPException(403, "These advanced TTS and spam-protection settings are available on the Pro plan.")
    events = await _normalise_events(payload.events, current_user, db)
    fields = ["tiktok_username","tts_provider","voice","fish_voice_id","fish_model","pitch","volume","speed","emoji_to_words","filter_profanity","require_command_prefix","max_message_length","comment_speech_enabled","comment_speech_template","minimum_account_age_days","spam_protection_enabled","block_repeated_words","auto_mute_repeat_offenders","spam_cooldown_seconds","spam_max_requests_per_minute"]
    for field in fields: setattr(prefs, field, getattr(payload, field))
    prefs.event_alerts = json.dumps(events)
    prefs.allowed_user_types = json.dumps(payload.allowed_user_types)
    prefs.blocked_words = json.dumps(payload.blocked_words)
    await db.commit(); await db.refresh(prefs)
    return _serialize(prefs)

@router.get("/v1/muted-users")
async def list_muted_users(current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    return (await db.execute(select(DBMutedUser).where(DBMutedUser.owner_id == current_user.id).order_by(DBMutedUser.created_at.desc()))).scalars().all()

@router.post("/v1/muted-users")
async def mute_user(payload: dict, current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    username = str(payload.get("tiktok_username", "")).strip()
    if not username: raise HTTPException(400, "tiktok_username is required.")
    item = DBMutedUser(owner_id=current_user.id, tiktok_user_id=payload.get("tiktok_user_id"), tiktok_username=username, reason=str(payload.get("reason", "manual")), created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(item); await db.commit(); await db.refresh(item); return item

@router.delete("/v1/muted-users/{muted_id}")
async def unmute_user(muted_id: int, current_user: DBUser=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    item = (await db.execute(select(DBMutedUser).where(DBMutedUser.id == muted_id, DBMutedUser.owner_id == current_user.id))).scalar_one_or_none()
    if item is None: raise HTTPException(404, "Muted user not found.")
    await db.delete(item); await db.commit(); return {"message": "User unmuted successfully."}
