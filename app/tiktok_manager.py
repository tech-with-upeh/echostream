import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict

from sqlalchemy.orm import Session
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, DisconnectEvent, FollowEvent, GiftEvent, LikeEvent

from app.database import SessionLocal
from app.live_runtime import mark_live_failed, mark_live_ready
from app.models import DBGiftPreference, DBMutedUser, DBUser, DBUserPreferences

active_sessions: Dict[int, asyncio.Queue] = {}
active_tiktok_clients: Dict[int, TikTokLiveClient] = {}
_request_times: dict[tuple[int, str], deque[float]] = defaultdict(deque)
_last_request_at: dict[tuple[int, str], float] = {}
_repeat_violations: dict[tuple[int, str], int] = defaultdict(int)
_warmup_tasks: dict[int, asyncio.Task] = {}
_intentional_stops: set[int] = set()
_PROFANITY = {"fuck", "fucking", "shit", "bitch", "asshole", "motherfucker"}
_INITIAL_SYNC_SECONDS = 2.0


def _load_user_and_preferences(user_id: int):
    db: Session = SessionLocal()
    try:
        return (
            db.query(DBUser).filter(DBUser.id == user_id).first(),
            db.query(DBUserPreferences).filter(DBUserPreferences.user_id == user_id).first(),
        )
    finally:
        db.close()


def _apply_template(template: str, username: str, comment: str = "", gift: str = "", count: int = 1, event_type: str = "") -> str:
    return ((template or "").replace("{{user}}", username).replace("{{username}}", username)
            .replace("{{comment}}", comment).replace("{{gift}}", gift)
            .replace("{{count}}", str(count)).replace("{{event}}", event_type))


def _normalise_words(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(x).strip().lower() for x in parsed if str(x).strip()]
    except (TypeError, json.JSONDecodeError):
        pass
    return [x.strip().lower() for x in str(value).split(",") if x.strip()]


def _contains_blocked_word(text: str, words: list[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text.lower()) for word in words)


def _contains_repeated_words(text: str, minimum: int = 3) -> bool:
    words = re.findall(r"[\w']+", text.lower())
    run = 1
    for previous, word in zip(words, words[1:]):
        run = run + 1 if word == previous else 1
        if run >= minimum:
            return True
    return False


def _user_role(event) -> str:
    user = event.user
    if bool(getattr(user, "is_moderator", False) or getattr(user, "is_mod", False)):
        return "moderators"
    if bool(getattr(user, "is_subscriber", False) or getattr(user, "is_sub", False)):
        return "subscribers"
    if bool(getattr(user, "is_follower", False) or getattr(user, "is_following", False)):
        return "followers"
    return "all"


def _allowed_user(event, prefs) -> bool:
    configured = set(_normalise_words(prefs.allowed_user_types))
    return not configured or "all" in configured or _user_role(event) in configured


def _muted(owner_id: int, tiktok_user_id: str | None, username: str) -> bool:
    db = SessionLocal()
    try:
        q = db.query(DBMutedUser).filter(DBMutedUser.owner_id == owner_id)
        return bool((tiktok_user_id and q.filter(DBMutedUser.tiktok_user_id == tiktok_user_id).first()) or q.filter(DBMutedUser.tiktok_username.ilike(username)).first())
    finally:
        db.close()


def _auto_mute(owner_id: int, tiktok_user_id: str | None, username: str) -> None:
    db = SessionLocal()
    try:
        q = db.query(DBMutedUser).filter(DBMutedUser.owner_id == owner_id)
        existing = q.filter(DBMutedUser.tiktok_user_id == tiktok_user_id).first() if tiktok_user_id else q.filter(DBMutedUser.tiktok_username.ilike(username)).first()
        if not existing:
            db.add(DBMutedUser(owner_id=owner_id, tiktok_user_id=tiktok_user_id, tiktok_username=username, reason="spam", created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            db.commit()
    finally:
        db.close()


def _spam_blocked(user_id: int, username: str, prefs) -> tuple[bool, bool]:
    if not prefs.spam_protection_enabled:
        return False, False
    key, now = (user_id, username.lower()), time.monotonic()
    cooldown = max(0, prefs.spam_cooldown_seconds)
    if cooldown and now - _last_request_at.get(key, 0.0) < cooldown:
        _repeat_violations[key] += 1
        return True, bool(prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3)
    stamps = _request_times[key]
    while stamps and now - stamps[0] >= 60:
        stamps.popleft()
    if len(stamps) >= max(1, prefs.spam_max_requests_per_minute):
        _repeat_violations[key] += 1
        return True, bool(prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3)
    stamps.append(now)
    _last_request_at[key] = now
    return False, False


def _gift_override(user_id: int, gift_id: str):
    db = SessionLocal()
    try:
        return db.query(DBGiftPreference).filter(DBGiftPreference.owner_id == user_id, DBGiftPreference.gift_id == gift_id).first()
    finally:
        db.close()


async def _enqueue_event_tts(queue, prefs, msg_id, event_type, username, gift="", count=1):
    if not prefs.event_speech_enabled:
        return
    text = _apply_template(prefs.event_speech_template, username, gift=gift, count=count, event_type=event_type)
    if text.strip():
        await queue.put({"id": msg_id, "event_type": event_type, "alert_type": "tts", "text": text, "voice": prefs.voice, "provider": prefs.tts_provider or "edge", "fish_voice_id": prefs.fish_voice_id, "fish_model": prefs.fish_model, "pitch": prefs.pitch, "speed": max(0.1, min(4.0, prefs.speed / 100.0)), "volume": prefs.volume, "username": username, "gift": gift, "count": count})


async def _enqueue_gift_alert(queue, user_id, prefs, msg_id, username, gift_id, gift_name, count):
    override = _gift_override(user_id, gift_id)
    if override is not None:
        if not override.enabled:
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
            return
        alert_type, template = prefs.gift_alert_type, prefs.gift_tts_template
        provider = prefs.gift_tts_provider or prefs.tts_provider or "edge"
        voice = prefs.gift_tts_voice or prefs.voice
        fish_voice_id = prefs.gift_fish_voice_id or prefs.fish_voice_id
        fish_model = prefs.gift_fish_model or prefs.fish_model
        system_sound_id, custom_audio_url = prefs.gift_system_sound_id, prefs.gift_custom_audio_url
        volume, speed, pitch = prefs.gift_volume, prefs.gift_speed, prefs.pitch
    item = {"id": msg_id, "event_type": "gift", "alert_type": alert_type, "text": "", "provider": provider, "voice": voice, "fish_voice_id": fish_voice_id, "fish_model": fish_model, "pitch": pitch, "speed": max(0.1, min(4.0, speed / 100.0)), "volume": volume, "system_sound_id": system_sound_id, "custom_audio_url": custom_audio_url, "username": username, "gift_id": gift_id, "gift": gift_name, "count": count}
    if alert_type == "tts":
        item["text"] = _apply_template(template or "{{user}} sent {{gift}}", username, gift=gift_name, count=count, event_type="gift")
        if not item["text"].strip():
            return
    elif alert_type == "system_sound" and not system_sound_id:
        return
    elif alert_type == "custom_audio" and not custom_audio_url:
        return
    await queue.put(item)


async def start_tiktok_session(user_id: int, tiktok_username: str) -> None:
    if user_id in active_tiktok_clients:
        return
    user, _ = _load_user_and_preferences(user_id)
    if user is None:
        mark_live_failed(user_id, active_sessions, "user not found")
        return
    _intentional_stops.discard(user_id)
    client = TikTokLiveClient(unique_id=tiktok_username)
    client.logger.setLevel(logging.WARNING)

    @client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent):
        async def _finish_initial_sync():
            try:
                await asyncio.sleep(_INITIAL_SYNC_SECONDS)
                if active_tiktok_clients.get(user_id) is client:
                    mark_live_ready(user_id, active_sessions)
            except asyncio.CancelledError:
                return
        old = _warmup_tasks.pop(user_id, None)
        if old:
            old.cancel()
        _warmup_tasks[user_id] = asyncio.create_task(_finish_initial_sync())
        print(f"[live] connected user_id={user_id}; syncing recent stream events")

    @client.on(CommentEvent)
    async def on_comment(event: CommentEvent):
        queue = active_sessions.get(user_id)
        if queue is None or not getattr(queue, "ready", False):
            return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs is None or not prefs.comment_speech_enabled:
            return
        username = (getattr(event.user, "nickname", None) or getattr(event.user, "unique_id", None) or "someone") if event.user else "someone"
        uid = str(getattr(event.user, "user_id", None) or getattr(event.user, "uid", None) or "") or None
        comment = (getattr(event, "comment", "") or "").strip()
        if not comment or _muted(user_id, uid, username) or not _allowed_user(event, prefs):
            return
        if prefs.require_command_prefix:
            if not comment.startswith("!"):
                return
            comment = comment[1:].lstrip()
        if not comment or len(comment) > max(1, prefs.max_message_length):
            return
        if _contains_blocked_word(comment, _normalise_words(prefs.blocked_words)):
            return
        if prefs.filter_profanity and _contains_blocked_word(comment, list(_PROFANITY)):
            return
        if prefs.spam_protection_enabled and prefs.block_repeated_words and _contains_repeated_words(comment):
            key = (user_id, username.lower()); _repeat_violations[key] += 1
            if prefs.auto_mute_repeat_offenders and _repeat_violations[key] >= 3: _auto_mute(user_id, uid, username)
            return
        blocked, mute = _spam_blocked(user_id, username, prefs)
        if blocked:
            if mute: _auto_mute(user_id, uid, username)
            return
        speech = _apply_template(prefs.comment_speech_template or "{{user}} said {{comment}}", username, comment=comment)
        if speech.strip():
            msg_id = str(getattr(getattr(event, "common", None), "msg_id", None) or id(event))
            await queue.put({"id": msg_id, "event_type": "comment", "alert_type": "tts", "text": speech, "source_text": comment, "username": username, "voice": prefs.voice, "provider": prefs.tts_provider or "edge", "fish_voice_id": prefs.fish_voice_id, "fish_model": prefs.fish_model, "pitch": prefs.pitch, "speed": max(0.1, min(4.0, prefs.speed / 100.0)), "volume": prefs.volume})

    @client.on(GiftEvent)
    async def on_gift(event: GiftEvent):
        queue = active_sessions.get(user_id)
        if queue is None or not getattr(queue, "ready", False) or getattr(event, "gift", None) is None or bool(getattr(event, "streaking", False)):
            return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs is None: return
        gift = event.gift
        await _enqueue_gift_alert(queue, user_id, prefs, str(getattr(getattr(event, "common", None), "msg_id", id(event))), getattr(event.user, "nickname", None) or "someone", str(getattr(gift, "id", None) or getattr(event, "gift_id", None) or ""), str(getattr(gift, "name", None) or "gift"), int(getattr(event, "repeat_count", 1) or 1))

    @client.on(FollowEvent)
    async def on_follow(event: FollowEvent):
        queue = active_sessions.get(user_id)
        if queue is None or not getattr(queue, "ready", False): return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs: await _enqueue_event_tts(queue, prefs, str(getattr(getattr(event, "common", None), "msg_id", id(event))), "follow", getattr(event.user, "nickname", None) or "someone")

    @client.on(LikeEvent)
    async def on_like(event: LikeEvent):
        queue = active_sessions.get(user_id)
        if queue is None or not getattr(queue, "ready", False): return
        _, prefs = _load_user_and_preferences(user_id)
        if prefs: await _enqueue_event_tts(queue, prefs, str(getattr(getattr(event, "common", None), "msg_id", id(event))), "like", getattr(event.user, "nickname", None) or "someone", count=int(getattr(event, "count", 1) or 1))

    @client.on(DisconnectEvent)
    async def on_disconnect(_event: DisconnectEvent):
        task = _warmup_tasks.pop(user_id, None)
        if task: task.cancel()
        active_tiktok_clients.pop(user_id, None)
        if user_id in _intentional_stops:
            _intentional_stops.discard(user_id)
            return
        mark_live_failed(user_id, active_sessions, "TikTok disconnected")

    async def _run():
        try:
            print(f"[live] connecting user_id={user_id} username=@{tiktok_username}")
            await client.start(fetch_gift_info=True)
        except Exception as exc:
            active_tiktok_clients.pop(user_id, None)
            mark_live_failed(user_id, active_sessions, str(exc))

    active_tiktok_clients[user_id] = client
    asyncio.create_task(_run())


async def stop_tiktok_session(user_id: int) -> None:
    _intentional_stops.add(user_id)
    task = _warmup_tasks.pop(user_id, None)
    if task: task.cancel()
    client = active_tiktok_clients.pop(user_id, None)
    if client is not None:
        await client.disconnect()
    for key in [key for key in _request_times if key[0] == user_id]:
        _request_times.pop(key, None); _last_request_at.pop(key, None); _repeat_violations.pop(key, None)
