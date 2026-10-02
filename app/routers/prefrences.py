import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_current_user, get_db
from app.models import DBAudioAsset, DBMutedUser, DBUser, DBUserPreferences
from app.schemas import PreferencesSchema, EventAlertPreferenceSchema
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Preferences"])
_ALLOWED_EVENT_TYPES = {"follow", "like", "gift"}
FREE_GIFT_ALERT_LIMIT = (
    3  # specific-gift alerts on the starter plan; "any gift"/like/follow don't count
)

# Fields that live directly on DBUserPreferences and can be partially updated.
_SIMPLE_FIELDS = [
    "tiktok_username",
    "tts_provider",
    "voice",
    "fish_voice_id",
    "fish_model",
    "pitch",
    "volume",
    "speed",
    "emoji_to_words",
    "filter_profanity",
    "require_command_prefix",
    "max_message_length",
    "comment_speech_enabled",
    "comment_speech_template",
    "minimum_account_age_days",
    "spam_protection_enabled",
    "block_repeated_words",
    "auto_mute_repeat_offenders",
    "spam_cooldown_seconds",
    "spam_max_requests_per_minute",
]

# Fields that are stored as JSON strings and need special handling.
_JSON_FIELDS = {"allowed_user_types", "blocked_words"}


def _parse_list(value, default):
    try:
        parsed = json.loads(value) if value else default
        return parsed if isinstance(parsed, list) else default
    except (TypeError, json.JSONDecodeError):
        return default


def _parse_events(value):
    try:
        parsed = json.loads(value) if value else {}
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


async def _get_or_create_preferences(current_user, db):
    prefs = (
        await db.execute(
            select(DBUserPreferences).where(
                DBUserPreferences.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id)
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
    return prefs


async def _validate_event(payload, current_user, db):
    if not payload.enabled:
        return None
    plan = current_user.plan.lower()
    if payload.alert_type == "tts":
        if not (payload.tts_template or "").strip():
            raise HTTPException(422, "TTS event alerts require a tts_template.")
        if payload.tts_provider == "fish" and plan != "pro":
            raise HTTPException(
                403, "Fish Audio event alerts are available on the Pro plan."
            )
        if payload.tts_provider == "fish" and not payload.fish_voice_id:
            raise HTTPException(422, "Fish event alerts require fish_voice_id.")
    elif payload.alert_type == "system_sound":
        if not payload.system_sound_id:
            raise HTTPException(
                422, "System sound event alerts require system_sound_id."
            )
    elif payload.alert_type == "custom_audio":
        if plan not in {"essential", "pro"}:
            raise HTTPException(
                403, "Custom audio is available on the Essential and Pro plans."
            )
        if not payload.custom_audio_id and not payload.custom_audio_url:
            raise HTTPException(
                422, "Custom audio event alerts require custom_audio_id."
            )
        if payload.custom_audio_id:
            asset = (
                await db.execute(
                    select(DBAudioAsset).where(
                        DBAudioAsset.id == payload.custom_audio_id,
                        DBAudioAsset.owner_user_id == current_user.id,
                    )
                )
            ).scalar_one_or_none()
            if asset is None:
                raise HTTPException(
                    403, "Custom audio must belong to the current user."
                )
            return asset
    return None


async def _normalise_events(events, current_user, db):
    is_starter = current_user.plan.lower() == "starter"

    result = {}
    seen_singletons = set()  # "follow", "like", or "gift:any" — at most one alert each
    custom_gift_count = 0

    for alert_id, payload in events.items():
        if payload.event_type not in _ALLOWED_EVENT_TYPES:
            raise HTTPException(422, f"Unsupported event type: {payload.event_type}")

        is_specific_gift = payload.event_type == "gift" and payload.gift_id
        if not is_specific_gift:
            singleton_key = (
                "gift:any" if payload.event_type == "gift" else payload.event_type
            )
            if singleton_key in seen_singletons:
                raise HTTPException(
                    422, f"Only one alert is allowed for {singleton_key}."
                )
            seen_singletons.add(singleton_key)
        else:
            custom_gift_count += 1
            if is_starter and custom_gift_count > FREE_GIFT_ALERT_LIMIT:
                raise HTTPException(
                    403,
                    f"The Starter plan allows up to {FREE_GIFT_ALERT_LIMIT} specific-gift alerts. Upgrade for unlimited alerts.",
                )

        asset = await _validate_event(payload, current_user, db)
        data = payload.model_dump()
        data["id"] = alert_id or payload.id or str(uuid.uuid4())
        if asset is not None:
            data["custom_audio_url"] = asset.public_url
        result[alert_id] = data

    return result


def _serialize(prefs):
    return PreferencesSchema(
        tiktok_username=prefs.tiktok_username,
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
        comment_speech_enabled=prefs.comment_speech_enabled,
        comment_speech_template=prefs.comment_speech_template,
        events=_parse_events(prefs.event_alerts),
        allowed_user_types=_parse_list(prefs.allowed_user_types, ["all"]),
        minimum_account_age_days=prefs.minimum_account_age_days,
        blocked_words=_parse_list(prefs.blocked_words, []),
        spam_protection_enabled=prefs.spam_protection_enabled,
        block_repeated_words=prefs.block_repeated_words,
        auto_mute_repeat_offenders=prefs.auto_mute_repeat_offenders,
        spam_cooldown_seconds=prefs.spam_cooldown_seconds,
        spam_max_requests_per_minute=prefs.spam_max_requests_per_minute,
    )


@router.get("/v1/preferences", response_model=PreferencesSchema)
async def get_preferences(
    current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return _serialize(await _get_or_create_preferences(current_user, db))


@router.put("/v1/preferences", response_model=PreferencesSchema)
async def update_preferences(
    payload: PreferencesSchema,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prefs = await _get_or_create_preferences(current_user, db)
    plan = current_user.plan.lower()
    is_pro = plan == "pro"

    # Only fields the client actually included in the request body are
    # considered "provided". Anything omitted falls back to Pydantic
    # defaults on `payload`, but we must never let those defaults overwrite
    # a field the client didn't intend to touch — that was the root cause
    # of partial updates (e.g. toggling a spam setting) silently reverting
    # unrelated fields (e.g. the selected cloned voice) back to defaults.
    provided = payload.model_dump(exclude_unset=True)

    if provided.get("tts_provider") == "fish" and not is_pro:
        raise HTTPException(403, "Fish Audio is available on the Pro plan.")

    # Plan-gated advanced settings: only enforce the check against fields
    # that were actually part of this request.
    pro_only_checks = {
        "emoji_to_words": lambda v: bool(v),
        "filter_profanity": lambda v: bool(v),
        "require_command_prefix": lambda v: bool(v),
        "minimum_account_age_days": lambda v: v != 1,
        "blocked_words": lambda v: bool(v),
        "spam_protection_enabled": lambda v: bool(v),
        "block_repeated_words": lambda v: not v,
        "auto_mute_repeat_offenders": lambda v: bool(v),
        "spam_cooldown_seconds": lambda v: v != 2,
        "spam_max_requests_per_minute": lambda v: v != 10,
    }
    if not is_pro:
        violates = any(
            check(provided[field])
            for field, check in pro_only_checks.items()
            if field in provided
        )
        if violates:
            raise HTTPException(
                403,
                "These advanced TTS and spam-protection settings are available on the Pro plan.",
            )

    for field in _SIMPLE_FIELDS:
        if field in provided:
            setattr(prefs, field, provided[field])

    if "events" in provided:
        events = await _normalise_events(payload.events, current_user, db)
        prefs.event_alerts = json.dumps(events)

    if "allowed_user_types" in provided:
        prefs.allowed_user_types = json.dumps(provided["allowed_user_types"])

    if "blocked_words" in provided:
        prefs.blocked_words = json.dumps(provided["blocked_words"])

    await db.commit()
    await db.refresh(prefs)
    return _serialize(prefs)


@router.get("/v1/muted-users")
async def list_muted_users(
    current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return (
        (
            await db.execute(
                select(DBMutedUser)
                .where(DBMutedUser.owner_id == current_user.id)
                .order_by(DBMutedUser.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


@router.post("/v1/muted-users")
async def mute_user(
    payload: dict,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    username = str(payload.get("tiktok_username", "")).strip()
    if not username:
        raise HTTPException(400, "tiktok_username is required.")
    item = DBMutedUser(
        owner_id=current_user.id,
        tiktok_user_id=payload.get("tiktok_user_id"),
        tiktok_username=username,
        reason=str(payload.get("reason", "manual")),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/v1/muted-users/{muted_id}")
async def unmute_user(
    muted_id: int,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = (
        await db.execute(
            select(DBMutedUser).where(
                DBMutedUser.id == muted_id, DBMutedUser.owner_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Muted user not found.")
    await db.delete(item)
    await db.commit()
    return {"message": "User unmuted successfully."}