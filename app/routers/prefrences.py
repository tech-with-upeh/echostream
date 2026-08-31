import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models import DBAudioAsset, DBMutedUser, DBUser, DBUserPreferences
from app.schemas import PreferencesSchema

router = APIRouter(tags=["Preferences"])

def _parse_list(value: str | None, default: list[str]) -> list[str]:
    if not value or not value.strip(): return default
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list): return [str(item) for item in parsed]
    except (json.JSONDecodeError, TypeError): pass
    return [item.strip() for item in value.split(",") if item.strip()] or default

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
        event_speech_template=prefs.event_speech_template, gift_alert_enabled=prefs.gift_alert_enabled, gift_alert_type=prefs.gift_alert_type,
        gift_tts_template=prefs.gift_tts_template, gift_tts_voice=prefs.gift_tts_voice, gift_tts_provider=prefs.gift_tts_provider,
        gift_fish_voice_id=prefs.gift_fish_voice_id, gift_fish_model=prefs.gift_fish_model, gift_system_sound_id=prefs.gift_system_sound_id,
        gift_custom_audio_id=prefs.gift_custom_audio_id, gift_custom_audio_url=prefs.gift_custom_audio_url, gift_volume=prefs.gift_volume, gift_speed=prefs.gift_speed,
        allowed_user_types=_parse_list(prefs.allowed_user_types,["all"]), minimum_account_age_days=prefs.minimum_account_age_days,
        blocked_words=_parse_list(prefs.blocked_words,[]), spam_protection_enabled=prefs.spam_protection_enabled,
        block_repeated_words=prefs.block_repeated_words, auto_mute_repeat_offenders=prefs.auto_mute_repeat_offenders,
        spam_cooldown_seconds=prefs.spam_cooldown_seconds, spam_max_requests_per_minute=prefs.spam_max_requests_per_minute,
    )

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
    prefs.allowed_user_types=json.dumps(payload.allowed_user_types); prefs.blocked_words=json.dumps(payload.blocked_words)
    await db.commit(); await db.refresh(prefs); return _serialize(prefs)

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
