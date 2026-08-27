import asyncio
import json
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict

from sqlalchemy.orm import Session
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, DisconnectEvent, FollowEvent, GiftEvent, LikeEvent

from app.database import SessionLocal
from app.models import DBGiftPreference, DBMutedUser, DBUser, DBUserPreferences

active_sessions: Dict[int, asyncio.Queue] = {}
active_tiktok_clients: Dict[int, TikTokLiveClient] = {}
_request_times: dict[tuple[int, str], deque[float]] = defaultdict(deque)
_last_request_at: dict[tuple[int, str], float] = {}
_repeat_violations: dict[tuple[int, str], int] = defaultdict(int)
_PROFANITY = {"fuck", "fucking", "shit", "bitch", "asshole", "motherfucker"}


def _load_user_and_preferences(user_id: int):
    db: Session = SessionLocal()
    try:
        user = db.query(DBUser).filter(DBUser.id == user_id).first()
        prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == user_id).first()
        return user, prefs
    finally:
        db.close()


def _apply_template(template: str, username: str, comment: str = "", gift: str = "", count: int = 1, event_type: str = "") -> str:
    return ((template or "").replace("{{user}}", username).replace("{{username}}", username)
            .replace("{{comment}}", comment).replace("{{gift}}", gift)
            .replace("{{count}}", str(count)).replace("{{event}}", event_type))


def _normalise_words(value: str | None) -> list[str]:
    if not value:
        return []
    try:
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
    run, previous = 1, words[0]
    for word in words[1:]:
        if word == previous:
            run += 1
            if run >= minimum:
                return True
        else:
            previous, run = word, 1
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
    return not configured or "all" in configured or _user_role(event) in configured


def _account_age_days(event: CommentEvent) -> int | None:
    created = getattr(event.user, "create_time", None) or getattr(event.user, "createTime", None)
    if created is None:
        return None
    try:
        created_dt = datetime.fromtimestamp(created, tz=timezone.utc) if isinstance(created, (int, float)) else created
        if getattr(created_dt, "tzinfo", None) is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
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
        if not existing:
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
    if cooldown and now - _last_request_at.get(key, 0.0) < cooldown:
        _repeat_violations[key] += 1
        return True, prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3
    timestamps = _request_times[key]
    while timestamps and now - timestamps[0] >= 60:
        timestamps.popleft()
    if len(timestamps) >= max(1, prefs.spam_max_requests_per_minute):
        _repeat_violations[key] += 1
        return True, prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3
    timestamps.append(now)
    _last_request_at[key] = now
    return False, False


def _gift_override(user_id: int, gift_id: str) -> DBGiftPreference | None:
    db: Session = SessionLocal()
    try:
        return db.query(DBGiftPreference).filter(DBGiftPreference.owner_id == user_id, DBGiftPreference.gift_id == gift_id).first()
    finally:
        db.close()


async def _enqueue_event_tts(queue: asyncio.Queue, prefs: DBUserPreferences, msg_id: str, event_type: str, username: str, gift: str = "", count: int = 1) -> None:
    if not prefs.event_speech_enabled:
        print(f"[tiktok:{event_type}] disabled")
        return
    text = _apply_template(prefs.event_speech_template, username, gift=gift, count=count, event_type=event_type)
    if not text.strip():
        print(f"[tiktok:{event_type}] empty template")
        return
    await queue.put({"id": msg_id, "event_type": event_type, "alert_type": "tts", "text": text, "voice": prefs.voice, "provider": prefs.tts_provider or "edge", "fish_voice_id": prefs.fish_voice_id, "fish_model": prefs.fish_model, "pitch": prefs.pitch, "speed": max(0.1, min(4.0, prefs.speed / 100.0)), "volume": prefs.volume, "username": username, "gift": gift, "count": count})
    print(f"[tiktok:{event_type}] queued id={msg_id} qsize={queue.qsize()}")


async def _enqueue_gift_alert(queue: asyncio.Queue, user_id: int, prefs: DBUserPreferences, msg_id: str, username: str, gift_id: str, gift_name: str, count: int) -> None:
    override = _gift_override(user_id, gift_id)
    if override is not None:
        if not override.enabled:
            print(f"[tiktok:gift] disabled gift_id={gift_id}")
            return
        alert_type = override.alert_type
        template = override.tts_template or prefs.gift_tts_template
        provider = override.tts_provider or prefs.gift_tts_provider or prefs.tts_provider or "edge"
        voice = override.voice or prefs.gift_tts_voice or prefs.voice
        fish_voice_id = override.fish_voice_id or prefs.gift_fish_voice_id or prefs.fish_voice_id
        fish_model = override.fish_model or prefs.gift_fish_model or prefs.fish_model
        system_sound_id = override.system_sound_id or prefs.gift_system_sound_id
        custom_audio_url = override.custom_audio_url or prefs.gift_custom_audio_url
        volume = override.volume if override.volume is not None else prefs.gift_volume
        speed = override.speed if override.speed is not None else prefs.gift_speed
        pitch = override.pitch or prefs.pitch
    else:
        if not prefs.gift_alert_enabled:
            print(f"[tiktok:gift] generic disabled gift_id={gift_id}")
            return
        alert_type = prefs.gift_alert_type
        template = prefs.gift_tts_template
        provider = prefs.gift_tts_provider or prefs.tts_provider or "edge"
        voice = prefs.gift_tts_voice or prefs.voice
        fish_voice_id = prefs.gift_fish_voice_id or prefs.fish_voice_id
        fish_model = prefs.gift_fish_model or prefs.fish_model
        system_sound_id = prefs.gift_system_sound_id
        custom_audio_url = prefs.gift_custom_audio_url
        volume = prefs.gift_volume
        speed = prefs.gift_speed
        pitch = prefs.pitch
    item = {"id": msg_id, "event_type": "gift", "alert_type": alert_type, "text": "", "provider": provider, "voice": voice, "fish_voice_id": fish_voice_id, "fish_model": fish_model, "pitch": pitch, "speed": max(0.1, min(4.0, speed / 100.0)), "volume": volume, "system_sound_id": system_sound_id, "custom_audio_url": custom_audio_url, "username": username, "gift_id": gift_id, "gift": gift_name, "count": count}
    if alert_type == "tts":
        item["text"] = _apply_template(template or "{{user}} sent {{gift}}", username, gift=gift_name, count=count, event_type="gift")
        if not item["text"].strip():
            print(f"[tiktok:gift] empty template gift_id={gift_id}")
            return
    elif alert_type == "system_sound" and not system_sound_id:
        print(f"[tiktok:gift] missing system sound gift_id={gift_id}")
        return
    elif alert_type == "custom_audio" and not custom_audio_url:
        print(f"[tiktok:gift] missing custom audio gift_id={gift_id}")
        return
    await queue.put(item)
    print(f"[tiktok:gift] queued id={msg_id} gift={gift_name!r} qsize={queue.qsize()}")


async def start_tiktok_session(user_id: int, tiktok_username: str) -> None:
    print(f"[tiktok] START user_id={user_id} username=@{tiktok_username}")
    if user_id in active_tiktok_clients:
        print(f"[tiktok] already active user_id={user_id}")
        return
    user, prefs = _load_user_and_preferences(user_id)
    if user is None:
        print(f"[tiktok] user not found user_id={user_id}")
        return
    client = TikTokLiveClient(unique_id=tiktok_username)
    print(f"[tiktok] client created user_id={user_id} client={type(client).__name__}")

    @client.on(CommentEvent)
    async def on_comment(event: CommentEvent):
        print(f"[tiktok:comment] RECEIVED user_id={user_id} event={event!r}")
        queue = active_sessions.get(user_id)
        if queue is None:
            print(f"[tiktok:comment] DROP no active queue user_id={user_id}")
            return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs is None:
            print(f"[tiktok:comment] DROP preferences missing user_id={user_id}")
            return
        if not prefs.comment_speech_enabled:
            print(f"[tiktok:comment] DROP comment speech disabled user_id={user_id}")
            return
        username = (getattr(event.user, "nickname", None) or getattr(event.user, "unique_id", None) or "someone") if event.user else "someone"
        tiktok_user_id = str(getattr(event.user, "user_id", None) or getattr(event.user, "uid", None) or "") or None
        comment = (getattr(event, "comment", "") or "").strip()
        print(f"[tiktok:comment] user={username!r} text={comment!r} qsize={queue.qsize()}")
        if _muted(user_id, tiktok_user_id, username):
            print(f"[tiktok:comment] DROP muted user={username!r}")
            return
        if not _allowed_user(event, prefs):
            print(f"[tiktok:comment] DROP role not allowed user={username!r}")
            return
        age_days = _account_age_days(event)
        if age_days is not None and age_days < max(0, prefs.minimum_account_age_days):
            print(f"[tiktok:comment] DROP account age={age_days} required={prefs.minimum_account_age_days}")
            return
        if prefs.require_command_prefix:
            if not comment.startswith("!"):
                print("[tiktok:comment] DROP command prefix required")
                return
            comment = comment[1:].lstrip()
            if not comment:
                print("[tiktok:comment] DROP empty command")
                return
        if len(comment) > max(1, prefs.max_message_length):
            print(f"[tiktok:comment] DROP too long len={len(comment)} max={prefs.max_message_length}")
            return
        blocked_words = _normalise_words(prefs.blocked_words)
        if blocked_words and _contains_blocked_word(comment, blocked_words):
            print("[tiktok:comment] DROP blocked word")
            return
        if prefs.filter_profanity and _contains_profanity(comment):
            print("[tiktok:comment] DROP profanity")
            return
        if prefs.spam_protection_enabled and prefs.block_repeated_words and _contains_repeated_words(comment):
            key = (user_id, username.lower())
            _repeat_violations[key] += 1
            print(f"[tiktok:comment] DROP repeated words violations={_repeat_violations[key]}")
            if prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3:
                _auto_mute(user_id, tiktok_user_id, username)
            return
        spammed, should_mute = _spam_blocked(user_id, username, prefs)
        if spammed:
            print(f"[tiktok:comment] DROP spam mute={should_mute}")
            if should_mute:
                _auto_mute(user_id, tiktok_user_id, username)
            return
        speech = _apply_template(prefs.comment_speech_template or "{{user}} said {{comment}}", username, comment=comment)
        if not speech.strip():
            print("[tiktok:comment] DROP empty speech template")
            return
        msg_id = str(getattr(getattr(event, "common", None), "msg_id", None) or id(event))
        await queue.put({"id": msg_id, "event_type": "comment", "alert_type": "tts", "text": speech, "source_text": comment, "username": username, "voice": prefs.voice, "provider": prefs.tts_provider or "edge", "fish_voice_id": prefs.fish_voice_id, "fish_model": prefs.fish_model, "pitch": prefs.pitch, "speed": max(0.1, min(4.0, prefs.speed / 100.0)), "volume": prefs.volume})
        print(f"[tiktok:comment] QUEUED id={msg_id} speech={speech!r} qsize={queue.qsize()}")

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent):
        print(f"[tiktok:gift] RECEIVED user_id={user_id}")
        queue = active_sessions.get(user_id)
        if queue is None or getattr(event, "gift", None) is None or bool(getattr(event, "streaking", False)):
            return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs is None: return
        gift = event.gift
        username = getattr(event.user, "nickname", None) or "someone"
        gift_id = str(getattr(gift, "id", None) or getattr(event, "gift_id", None) or "")
        gift_name = str(getattr(gift, "name", None) or "gift")
        count = int(getattr(event, "repeat_count", 1) or 1)
        await _enqueue_gift_alert(queue, user_id, prefs, str(getattr(getattr(event, "common", None), "msg_id", id(event))), username, gift_id, gift_name, count)

    @client.on(FollowEvent)
    async def on_follow(event: FollowEvent):
        print(f"[tiktok:follow] RECEIVED user_id={user_id}")
        queue = active_sessions.get(user_id)
        if queue is None: return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs: await _enqueue_event_tts(queue, prefs, str(getattr(getattr(event, "common", None), "msg_id", id(event))), "follow", getattr(event.user, "nickname", None) or "someone")

    @client.on(LikeEvent)
    async def on_like(event: LikeEvent):
        print(f"[tiktok:like] RECEIVED user_id={user_id}")
        queue = active_sessions.get(user_id)
        if queue is None: return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs: await _enqueue_event_tts(queue, prefs, str(getattr(getattr(event, "common", None), "msg_id", id(event))), "like", getattr(event.user, "nickname", None) or "someone", count=int(getattr(event, "count", 1) or 1))

    @client.on(DisconnectEvent)
    async def on_disconnect(_event: DisconnectEvent):
        print(f"[tiktok] DISCONNECTED user_id={user_id}")
        active_tiktok_clients.pop(user_id, None)

    async def _run():
        try:
            print(f"[tiktok] CONNECTING user_id={user_id} username=@{tiktok_username}")
            await client.start(fetch_gift_info=True)
        except Exception as exc:
            print(f"[tiktok] FAILED user_id={user_id} username=@{tiktok_username}: {exc!r}")
            active_tiktok_clients.pop(user_id, None)
            queue = active_sessions.get(user_id)
            if queue is not None:
                await queue.put({"id": "tiktok-connect-error", "event_type": "error", "text": "", "voice": "en-US-GuyNeural"})

    active_tiktok_clients[user_id] = client
    asyncio.create_task(_run())


async def stop_tiktok_session(user_id: int) -> None:
    print(f"[tiktok] STOP user_id={user_id}")
    client = active_tiktok_clients.pop(user_id, None)
    if client is not None:
        await client.disconnect()
    for key in [key for key in _request_times if key[0] == user_id]:
        _request_times.pop(key, None)
        _last_request_at.pop(key, None)
        _repeat_violations.pop(key, None)
