import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import DBUser, DBUserPreferences
from app.schemas import PreferencesSchema

router = APIRouter(tags=["Preferences"])

PRO_ONLY_FIELDS = {
    "emoji_to_words",
    "filter_profanity",
    "require_command_prefix",
    "speech_prefix_enabled",
    "speech_prefix_template",
    "minimum_account_age_days",
    "blocked_words",
    "spam_protection_enabled",
    "block_repeated_words",
    "auto_mute_repeat_offenders",
    "spam_cooldown_seconds",
    "spam_max_requests_per_minute",
}


def _get_or_create_preferences(current_user: DBUser, db: Session) -> DBUserPreferences:
    prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == current_user.id).first()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def _serialize(prefs: DBUserPreferences) -> PreferencesSchema:
    return PreferencesSchema(
        tiktok_username=prefs.tiktok_username,
        comment_prefix=prefs.comment_prefix,
        comment_suffix=prefs.comment_suffix,
        tts_provider=prefs.tts_provider,
        voice=prefs.voice,
        fish_voice_id=prefs.fish_voice_id,
        fish_model=prefs.fish_model,
        pitch=prefs.pitch,
        volume=prefs.volume,
        speed=prefs.speed,
        emoji_to_words=prefs.emoji_to_words,
        filter_profanity=prefs.filter_profanity,
        require_command_prefix=prefs.require_command_prefix,
        max_message_length=prefs.max_message_length,
        speech_prefix_enabled=prefs.speech_prefix_enabled,
        speech_prefix_template=prefs.speech_prefix_template,
        allowed_user_types=json.loads(prefs.allowed_user_types or '["all"]'),
        minimum_account_age_days=prefs.minimum_account_age_days,
        blocked_words=json.loads(prefs.blocked_words or "[]"),
        spam_protection_enabled=prefs.spam_protection_enabled,
        block_repeated_words=prefs.block_repeated_words,
        auto_mute_repeat_offenders=prefs.auto_mute_repeat_offenders,
        spam_cooldown_seconds=prefs.spam_cooldown_seconds,
        spam_max_requests_per_minute=prefs.spam_max_requests_per_minute,
    )


@router.get("/v1/preferences", response_model=PreferencesSchema)
def get_preferences(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _serialize(_get_or_create_preferences(current_user, db))


@router.put("/v1/preferences", response_model=PreferencesSchema)
def update_preferences(
    payload: PreferencesSchema,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prefs = _get_or_create_preferences(current_user, db)
    is_pro = current_user.plan.lower() == "pro"

    if payload.tts_provider == "fish" and not is_pro:
        raise HTTPException(status_code=403, detail="Fish Audio is available on the Pro plan.")
    if payload.fish_model not in {"s2-pro", "s2.1-pro-free"}:
        raise HTTPException(status_code=400, detail="Unsupported Fish Audio model.")
    if any(field in PRO_ONLY_FIELDS for field in PRO_ONLY_FIELDS if field):
        if not is_pro and any([
            payload.emoji_to_words,
            payload.filter_profanity,
            payload.require_command_prefix,
            payload.speech_prefix_enabled,
            payload.minimum_account_age_days != 1,
            bool(payload.blocked_words),
            payload.spam_protection_enabled,
            not payload.block_repeated_words,
            payload.auto_mute_repeat_offenders,
            payload.spam_cooldown_seconds != 2,
            payload.spam_max_requests_per_minute != 10,
        ]):
            raise HTTPException(status_code=403, detail="These advanced TTS and spam-protection settings are available on the Pro plan.")

    prefs.tiktok_username = payload.tiktok_username
    prefs.comment_prefix = payload.comment_prefix
    prefs.comment_suffix = payload.comment_suffix
    prefs.tts_provider = payload.tts_provider
    prefs.voice = payload.voice
    prefs.fish_voice_id = payload.fish_voice_id
    prefs.fish_model = payload.fish_model
    prefs.pitch = payload.pitch
    prefs.volume = payload.volume
    prefs.speed = payload.speed
    prefs.emoji_to_words = payload.emoji_to_words
    prefs.filter_profanity = payload.filter_profanity
    prefs.require_command_prefix = payload.require_command_prefix
    prefs.max_message_length = payload.max_message_length
    prefs.speech_prefix_enabled = payload.speech_prefix_enabled
    prefs.speech_prefix_template = payload.speech_prefix_template
    prefs.allowed_user_types = json.dumps(payload.allowed_user_types)
    prefs.minimum_account_age_days = payload.minimum_account_age_days
    prefs.blocked_words = json.dumps(payload.blocked_words)
    prefs.spam_protection_enabled = payload.spam_protection_enabled
    prefs.block_repeated_words = payload.block_repeated_words
    prefs.auto_mute_repeat_offenders = payload.auto_mute_repeat_offenders
    prefs.spam_cooldown_seconds = payload.spam_cooldown_seconds
    prefs.spam_max_requests_per_minute = payload.spam_max_requests_per_minute
    db.commit()
    db.refresh(prefs)
    return _serialize(prefs)


@router.get("/v1/muted-users")
def list_muted_users(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import DBMutedUser
    return db.query(DBMutedUser).filter(DBMutedUser.owner_id == current_user.id).order_by(DBMutedUser.created_at.desc()).all()


@router.post("/v1/muted-users")
def mute_user(payload: dict, current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    from app.models import DBMutedUser
    username = str(payload.get("tiktok_username", "")).strip()
    if not username:
        raise HTTPException(status_code=400, detail="tiktok_username is required.")
    item = DBMutedUser(owner_id=current_user.id, tiktok_user_id=payload.get("tiktok_user_id"), tiktok_username=username, reason=str(payload.get("reason", "manual")), created_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/v1/muted-users/{muted_id}")
def unmute_user(muted_id: int, current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import DBMutedUser
    item = db.query(DBMutedUser).filter(DBMutedUser.id == muted_id, DBMutedUser.owner_id == current_user.id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Muted user not found.")
    db.delete(item)
    db.commit()
    return {"message": "User unmuted successfully."}
