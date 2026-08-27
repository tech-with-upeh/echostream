import asyncio
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict

from sqlalchemy.orm import Session
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, DisconnectEvent, FollowEvent, GiftEvent, LikeEvent

from app.database import SessionLocal
from app.models import DBMutedUser, DBUser, DBUserPreferences

active_sessions: Dict[int, asyncio.Queue] = {}
active_tiktok_clients: Dict[int, TikTokLiveClient] = {}

_request_times: dict[tuple[int, str], deque[float]] = defaultdict(deque)
_last_request_at: dict[tuple[int, str], float] = {}
_repeat_violations: dict[tuple[int, str], int] = defaultdict(int)

_PROFANITY = {"fuck", "fucking", "shit", "bitch", "asshole", "motherfucker"}


def _load_user_and_preferences(user_id: int) -> tuple[DBUser | None, DBUserPreferences | None]:
    db: Session = SessionLocal()
    try:
        user = db.query(DBUser).filter(DBUser.id == user_id).first()
        prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == user_id).first()
        return user, prefs
    finally:
        db.close()


def _apply_template(template: str, username: str, comment: str = "", gift: str = "", count: int = 1, event_type: str = "") -> str:
    return (
        (template or "")
        .replace("{{user}}", username)
        .replace("{{username}}", username)
        .replace("{{comment}}", comment)
        .replace("{{gift}}", gift)
        .replace("{{count}}", str(count))
        .replace("{{event}}", event_type)
    )


def _normalise_words(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        import json
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip().lower() for item in parsed if str(item).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def _contains_blocked_word(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", lowered) for word in words)


def _contains_repeated_words(text: str, minimum: int = 3) -> bool:
    words = re.findall(r"[\w']+", text.lower())
    if len(words) < minimum:
        return False
    run = 1
    previous = words[0]
    for word in words[1:]:
        if word == previous:
            run += 1
            if run >= minimum:
                return True
        else:
            previous = word
            run = 1
    return False


def _contains_profanity(text: str) -> bool:
    return _contains_blocked_word(text, list(_PROFANITY))


def _user_role(event: CommentEvent) -> str:
    user = event.user
    if bool(getattr(user, "is_moderator", False) or getattr(user, "is_mod", False)):
        return "moderators"
    if bool(getattr(user, "is_subscriber", False) or getattr(user, "is_sub", False)):
        return "subscribers"
    if bool(getattr(user, "is_follower", False) or getattr(user, "is_following", False)):
        return "followers"
    return "all"


def _allowed_user(event: CommentEvent, prefs: DBUserPreferences) -> bool:
    configured = set(_normalise_words(prefs.allowed_user_types))
    if not configured or "all" in configured:
        return True
    return _user_role(event) in configured


def _account_age_days(event: CommentEvent) -> int | None:
    user = event.user
    created = getattr(user, "create_time", None) or getattr(user, "createTime", None)
    if created is None:
        return None
    try:
        if isinstance(created, (int, float)):
            created_dt = datetime.fromtimestamp(created, tz=timezone.utc)
        else:
            created_dt = created if getattr(created, "tzinfo", None) else created.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - created_dt).days)
    except (TypeError, ValueError, OverflowError):
        return None


def _muted(user_id: int, tiktok_user_id: str | None, username: str) -> bool:
    db: Session = SessionLocal()
    try:
        query = db.query(DBMutedUser).filter(DBMutedUser.owner_id == user_id)
        if tiktok_user_id and query.filter(DBMutedUser.tiktok_user_id == tiktok_user_id).first():
            return True
        return query.filter(DBMutedUser.tiktok_username.ilike(username)).first() is not None
    finally:
        db.close()


def _auto_mute(user_id: int, tiktok_user_id: str | None, username: str) -> None:
    db: Session = SessionLocal()
    try:
        query = db.query(DBMutedUser).filter(DBMutedUser.owner_id == user_id)
        existing = query.filter(DBMutedUser.tiktok_user_id == tiktok_user_id).first() if tiktok_user_id else query.filter(DBMutedUser.tiktok_username.ilike(username)).first()
        if existing:
            return
        db.add(DBMutedUser(owner_id=user_id, tiktok_user_id=tiktok_user_id, tiktok_username=username, reason="spam", created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        db.commit()
    finally:
        db.close()


def _spam_blocked(user_id: int, username: str, prefs: DBUserPreferences) -> tuple[bool, bool]:
    if not prefs.spam_protection_enabled:
        return False, False
    key = (user_id, username.lower())
    now = time.monotonic()
    cooldown = max(0, prefs.spam_cooldown_seconds)
    max_per_minute = max(1, prefs.spam_max_requests_per_minute)
    if cooldown and now - _last_request_at.get(key, 0.0) < cooldown:
        _repeat_violations[key] += 1
        return True, prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3
    timestamps = _request_times[key]
    while timestamps and now - timestamps[0] >= 60:
        timestamps.popleft()
    if len(timestamps) >= max_per_minute:
        _repeat_violations[key] += 1
        return True, prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3
    timestamps.append(now)
    _last_request_at[key] = now
    return False, False


async def _enqueue_event_tts(queue: asyncio.Queue, prefs: DBUserPreferences, msg_id: str, event_type: str, username: str, gift: str = "", count: int = 1) -> None:
    if not prefs.event_speech_enabled:
        return
    text = _apply_template(prefs.event_speech_template, username, gift=gift, count=count, event_type=event_type)
    if not text.strip():
        return
    await queue.put({
        "id": msg_id,
        "event_type": event_type,
        "text": text,
        "voice": prefs.voice,
        "provider": prefs.tts_provider or "edge",
        "fish_voice_id": prefs.fish_voice_id,
        "fish_model": prefs.fish_model,
        "pitch": prefs.pitch,
        "speed": max(0.1, min(4.0, prefs.speed / 100.0)),
        "volume": prefs.volume,
        "username": username,
        "gift": gift,
        "count": count,
    })


async def start_tiktok_session(user_id: int, tiktok_username: str) -> None:
    if user_id in active_tiktok_clients:
        return
    user, prefs = _load_user_and_preferences(user_id)
    if user is None:
        return
    if prefs is None:
        prefs = DBUserPreferences(user_id=user_id)

    client = TikTokLiveClient(unique_id=tiktok_username)

    @client.on(CommentEvent)
    async def on_comment(event: CommentEvent):
        queue = active_sessions.get(user_id)
        if queue is None:
            return
        _, current_prefs = _load_user_and_preferences(user_id)
        if current_prefs is not None:
            prefs = current_prefs
        msg_id = str(event.common.msg_id) if event.common else str(id(event))
        username = event.user.nickname if event.user else "someone"
        tiktok_user_id = str(getattr(event.user, "user_id", None) or getattr(event.user, "uid", None) or "") or None
        comment = (event.comment or "").strip()
        if not prefs.comment_speech_enabled:
            return
        if _muted(user_id, tiktok_user_id, username) or not _allowed_user(event, prefs):
            return
        age_days = _account_age_days(event)
        if age_days is not None and age_days < max(0, prefs.minimum_account_age_days):
            return
        if prefs.require_command_prefix:
            prefix = "!"
            if not comment.startswith(prefix):
                return
            comment = comment[len(prefix):].lstrip()
            if not comment:
                return
        if len(comment) > max(1, prefs.max_message_length):
            return
        blocked_words = _normalise_words(prefs.blocked_words)
        if blocked_words and _contains_blocked_word(comment, blocked_words):
            return
        if prefs.filter_profanity and _contains_profanity(comment):
            return
        if prefs.spam_protection_enabled and prefs.block_repeated_words and _contains_repeated_words(comment):
            key = (user_id, username.lower())
            _repeat_violations[key] += 1
            if prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3:
                _auto_mute(user_id, tiktok_user_id, username)
            return
        spammed, should_mute = _spam_blocked(user_id, username, prefs)
        if spammed:
            if should_mute:
                _auto_mute(user_id, tiktok_user_id, username)
            return
        spoken_comment = _apply_template(prefs.comment_speech_template, username, comment=comment)
        await queue.put({
            "id": msg_id,
            "event_type": "comment",
            "text": spoken_comment,
            "voice": prefs.voice,
            "provider": prefs.tts_provider or "edge",
            "fish_voice_id": prefs.fish_voice_id,
            "fish_model": prefs.fish_model,
            "pitch": prefs.pitch,
            "speed": max(0.1, min(4.0, prefs.speed / 100.0)),
            "volume": prefs.volume,
        })

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent):
        queue = active_sessions.get(user_id)
        if queue is None:
            return
        _, current_prefs = _load_user_and_preferences(user_id)
        if current_prefs is None:
            return
        gift = getattr(event, "gift", None)
        if gift is None:
            return
        if bool(getattr(event, "streaking", False)):
            return
        username = event.user.nickname if event.user else "someone"
        gift_name = str(getattr(gift, "name", None) or getattr(gift, "gift_name", None) or "gift")
        count = int(getattr(event, "repeat_count", 1) or 1)
        msg_id = str(event.common.msg_id) if getattr(event, "common", None) else str(id(event))
        await _enqueue_event_tts(queue, current_prefs, msg_id, "gift", username, gift_name, count)

    @client.on(FollowEvent)
    async def on_follow(event: FollowEvent):
        queue = active_sessions.get(user_id)
        if queue is None:
            return
        _, current_prefs = _load_user_and_preferences(user_id)
        if current_prefs is None:
            return
        username = event.user.nickname if event.user else "someone"
        msg_id = str(event.common.msg_id) if getattr(event, "common", None) else str(id(event))
        await _enqueue_event_tts(queue, current_prefs, msg_id, "follow", username)

    @client.on(LikeEvent)
    async def on_like(event: LikeEvent):
        queue = active_sessions.get(user_id)
        if queue is None:
            return
        _, current_prefs = _load_user_and_preferences(user_id)
        if current_prefs is None:
            return
        username = event.user.nickname if event.user else "someone"
        count = int(getattr(event, "count", 1) or 1)
        msg_id = str(event.common.msg_id) if getattr(event, "common", None) else str(id(event))
        await _enqueue_event_tts(queue, current_prefs, msg_id, "like", username, count=count)

    @client.on(DisconnectEvent)
    async def on_disconnect(_event: DisconnectEvent):
        active_tiktok_clients.pop(user_id, None)

    async def _run():
        try:
            await client.start()
        except Exception as exc:
            print(f"[tiktok_manager] Failed to connect for user {user_id} (@{tiktok_username}): {exc!r}")
            active_tiktok_clients.pop(user_id, None)
            queue = active_sessions.get(user_id)
            if queue is not None:
                await queue.put({"id": "tiktok-connect-error", "event_type": "error", "text": "", "voice": "en-US-GuyNeural"})

    active_tiktok_clients[user_id] = client
    asyncio.create_task(_run())


async def stop_tiktok_session(user_id: int) -> None:
    client = active_tiktok_clients.pop(user_id, None)
    if client is not None:
        await client.disconnect()
    for key in [key for key in _request_times if key[0] == user_id]:
        _request_times.pop(key, None)
        _last_request_at.pop(key, None)
        _repeat_violations.pop(key, None)
