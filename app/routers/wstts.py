import asyncio
import json
import time

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.live_runtime import acquire_tts_owner, event_channel, get_live_status, refresh_tts_owner, release_tts_owner
from app.models import DBAudioAsset, DBUser, DBUserPreferences
from app.fish_audio import FishAudioError, stream_tts
from app.routers.voice import tts_streaming_generator
from app.redis_store import get_redis

router = APIRouter(tags=["Text-to-Speech (Live)"])


async def _get_user_from_token(token: str):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None or payload.get("type") != "access" or not payload.get("session_id"):
            return None
        user_id = int(user_id)
    except (InvalidTokenError, ValueError, TypeError):
        return None
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(DBUser).where(DBUser.id == user_id))).scalar_one_or_none()


async def _get_preferences(user_id: int):
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(DBUserPreferences).where(DBUserPreferences.user_id == user_id))).scalar_one_or_none()


async def _load_sound_catalog(user_id: int) -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(DBAudioAsset).where((DBAudioAsset.owner_user_id.is_(None)) | (DBAudioAsset.owner_user_id == user_id)))
        return {str(asset.id): asset.public_url for asset in result.scalars().all()}


def _status_payload(item: dict, event: str, sound_catalog: dict[str, str] | None = None) -> dict:
    event_type = item.get("event_type", "comment")
    payload = {"type": "status", "id": item.get("id"), "event": event, "event_type": event_type, "alert_type": item.get("alert_type", "tts")}
    if event_type == "comment":
        payload["comment"] = item.get("source_text", item.get("text", ""))
    if event_type in {"gift", "follow", "like"}:
        payload.update({"username": item.get("username"), "gift": item.get("gift"), "gift_id": item.get("gift_id"), "count": item.get("count", 1)})
    if item.get("alert_type") == "system_sound":
        sound_id = item.get("system_sound_id")
        payload["system_sound_id"] = sound_id
        payload["system_sound_url"] = (sound_catalog or {}).get(str(sound_id))
    if item.get("alert_type") == "custom_audio":
        payload["custom_audio_url"] = item.get("custom_audio_url")
    return payload


@router.websocket("/ws/v1/tts")
async def live_tts_socket(websocket: WebSocket, token: str = Query(...)):
    user = await _get_user_from_token(token)
    if user is None:
        await websocket.close(code=4401)
        return

    state = await get_live_status(user.id)
    if state.get("status") not in {"connecting", "ready"}:
        await websocket.close(code=4409, reason="Start the TikTok live session before connecting the TTS stream.")
        return
    if not await acquire_tts_owner(user.id):
        await websocket.close(code=4409, reason="A TTS stream is already connected for this account.")
        return

    await websocket.accept()
    local_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    pubsub = get_redis().pubsub()
    stop_event = asyncio.Event()
    heartbeat_task = None

    try:
        prefs = await _get_preferences(user.id)
        username = prefs.tiktok_username if prefs else state.get("username")
        sound_catalog = await _load_sound_catalog(user.id)
        await websocket.send_json({"type": "ready", "message": "WebSocket connected", "tiktok_active": True, "tiktok_username": username})
        await websocket.send_json({"type": "tiktok_status", "status": state.get("status", "connecting"), "username": username})

        await pubsub.subscribe(event_channel(user.id))

        async def redis_reader():
            try:
                async for message in pubsub.listen():
                    if stop_event.is_set():
                        return
                    if message.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                    except (TypeError, ValueError):
                        continue
                    if payload.get("type") == "tts_event" and payload.get("item"):
                        try:
                            local_queue.put_nowait(payload["item"])
                        except asyncio.QueueFull:
                            try:
                                local_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            local_queue.put_nowait(payload["item"])
                    elif payload.get("type") == "live_state":
                        await websocket.send_json({"type": "tiktok_status", "status": payload.get("status"), "username": payload.get("username"), "error": payload.get("error")})
                    elif payload.get("type") == "live_error":
                        await websocket.send_json({"type": "error", "detail": payload.get("error", "TikTok session failed")})
            except asyncio.CancelledError:
                return

        async def reader():
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        await websocket.send_json({"type": "error", "detail": "Invalid JSON."})
                        continue
                    if msg.get("type") not in {"test", "speak"}:
                        await websocket.send_json({"type": "error", "detail": "Unknown message type."})
                        continue

                    bucket = int(time.time()) // max(1, settings.RATE_LIMIT_WINDOW_SECONDS)
                    rate_key = f"echostream:ratelimit:ws:{user.id}:{bucket}"
                    count = await get_redis().incr(rate_key)
                    if count == 1:
                        await get_redis().expire(rate_key, settings.RATE_LIMIT_WINDOW_SECONDS + 1)
                    if count > settings.RATE_LIMIT_WS_MESSAGES_PER_MINUTE:
                        await websocket.send_json({"type": "error", "detail": "Too many WebSocket messages. Please slow down."})
                        continue

                    text = (msg.get("text") or ("EchoStream WebSocket test" if msg.get("type") == "test" else "")).strip()
                    if not text:
                        await websocket.send_json({"type": "error", "detail": "Text cannot be empty."})
                        continue
                    current_prefs = await _get_preferences(user.id)
                    if msg.get("type") == "test" and current_prefs is None:
                        await websocket.send_json({"type": "error", "detail": "Preferences not found."})
                        continue
                    await local_queue.put({
                        "id": msg.get("id") or ("ws-test" if msg.get("type") == "test" else None),
                        "event_type": "test" if msg.get("type") == "test" else msg.get("event_type", "comment"),
                        "alert_type": "tts",
                        "text": text,
                        "provider": (msg.get("provider") or (current_prefs.tts_provider if current_prefs else "edge")).lower(),
                        "voice": msg.get("voice") or (current_prefs.voice if current_prefs else "en-US-GuyNeural"),
                        "fish_voice_id": current_prefs.fish_voice_id if current_prefs else None,
                        "fish_model": msg.get("fish_model") or (current_prefs.fish_model if current_prefs else settings.FISH_AUDIO_PRO_MODEL),
                        "pitch": current_prefs.pitch if current_prefs else "+0Hz",
                        "speed": float(msg.get("speed", 1.0)),
                        "volume": current_prefs.volume if current_prefs else 100,
                    })
            except WebSocketDisconnect:
                return

        async def writer():
            while True:
                item = await local_queue.get()
                try:
                    await websocket.send_json(_status_payload(item, "start", sound_catalog))
                    alert_type = item.get("alert_type", "tts")
                    if alert_type in {"system_sound", "custom_audio"}:
                        await websocket.send_json(_status_payload(item, "play", sound_catalog))
                    elif item.get("provider") == "fish":
                        if user.plan.lower() != "pro":
                            raise PermissionError("Fish Audio is available on the Pro plan.")
                        async for chunk in stream_tts(item["text"], reference_id=item.get("fish_voice_id") or item.get("voice"), model=item.get("fish_model") or settings.FISH_AUDIO_PRO_MODEL, speed=item.get("speed", 1.0)):
                            await websocket.send_bytes(chunk)
                    elif item.get("provider") == "edge":
                        async for chunk in tts_streaming_generator(item["text"], item["voice"], item.get("pitch", "+0Hz")):
                            await websocket.send_bytes(chunk)
                    else:
                        raise ValueError("Unsupported TTS provider.")
                    await websocket.send_json(_status_payload(item, "end", sound_catalog))
                except (FishAudioError, PermissionError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "id": item.get("id"), "detail": str(exc)})
                except Exception as exc:
                    await websocket.send_json({"type": "error", "id": item.get("id"), "detail": str(exc)})

        async def heartbeat():
            while not stop_event.is_set():
                if not await refresh_tts_owner(user.id):
                    return
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass

        redis_task = asyncio.create_task(redis_reader())
        reader_task = asyncio.create_task(reader())
        writer_task = asyncio.create_task(writer())
        heartbeat_task = asyncio.create_task(heartbeat())
        done, pending = await asyncio.wait({redis_task, reader_task, writer_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        stop_event.set()
        if heartbeat_task:
            heartbeat_task.cancel()
        await pubsub.close()
        await release_tts_owner(user.id)
