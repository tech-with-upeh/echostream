import asyncio
import json

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DBUser, DBUserPreferences
from app.fish_audio import FishAudioError, stream_tts
from app.routers.voice import tts_streaming_generator
from app.tiktok_manager import active_sessions

router = APIRouter(tags=["Text-to-Speech (Live)"])


async def _get_user_from_token(token: str):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            return None
        user_id = int(user_id)
    except (InvalidTokenError, ValueError, TypeError):
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(DBUser).where(DBUser.id == user_id))
        return result.scalar_one_or_none()


async def _get_preferences(user_id: int):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBUserPreferences).where(DBUserPreferences.user_id == user_id)
        )
        return result.scalar_one_or_none()


def _status_payload(item: dict, event: str) -> dict:
    event_type = item.get("event_type", "comment")
    payload = {"type": "status", "id": item.get("id"), "event": event,
               "event_type": event_type, "alert_type": item.get("alert_type", "tts")}
    if event_type == "comment":
        payload["comment"] = item.get("source_text", item.get("text", ""))
    if event_type in {"gift", "follow", "like"}:
        payload.update({"username": item.get("username"), "gift": item.get("gift"),
                        "gift_id": item.get("gift_id"), "count": item.get("count", 1)})
    if item.get("alert_type") == "system_sound":
        payload["system_sound_id"] = item.get("system_sound_id")
    if item.get("alert_type") == "custom_audio":
        payload["custom_audio_url"] = item.get("custom_audio_url")
    return payload


@router.websocket("/ws/v1/tts")
async def live_tts_socket(websocket: WebSocket, token: str = Query(...)):
    user = None
    queue = None
    try:
        user = await _get_user_from_token(token)
        if user is None:
            await websocket.close(code=4401)
            return

        await websocket.accept()
        queue = active_sessions.get(user.id)
        tiktok_active = queue is not None

        prefs = await _get_preferences(user.id)
        username = prefs.tiktok_username if prefs else None

        await websocket.send_json({"type": "ready", "message": "WebSocket connected",
                                   "tiktok_active": tiktok_active, "tiktok_username": username})
        await websocket.send_json({"type": "tiktok_status",
                                   "status": "active" if tiktok_active else "not_started",
                                   "username": username})

        if queue is None:
            await websocket.send_json({"type": "error", "detail": "Start the TikTok live session before connecting the TTS stream."})
            await websocket.close(code=4409)
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

                    text = (msg.get("text") or ("EchoStream WebSocket test" if msg.get("type") == "test" else "")).strip()
                    if not text:
                        await websocket.send_json({"type": "error", "detail": "Text cannot be empty."})
                        continue

                    current_prefs = await _get_preferences(user.id)
                    if msg.get("type") == "test" and current_prefs is None:
                        await websocket.send_json({"type": "error", "detail": "Preferences not found."})
                        continue

                    await queue.put({"id": msg.get("id") or ("ws-test" if msg.get("type") == "test" else None),
                                     "event_type": "test" if msg.get("type") == "test" else msg.get("event_type", "comment"),
                                     "alert_type": "tts", "text": text,
                                     "provider": (msg.get("provider") or (current_prefs.tts_provider if current_prefs else "edge")).lower(),
                                     "voice": msg.get("voice") or (current_prefs.voice if current_prefs else "en-US-GuyNeural"),
                                     "fish_voice_id": current_prefs.fish_voice_id if current_prefs else None,
                                     "fish_model": msg.get("fish_model") or (current_prefs.fish_model if current_prefs else settings.FISH_AUDIO_PRO_MODEL),
                                     "pitch": current_prefs.pitch if current_prefs else "+0Hz",
                                     "speed": float(msg.get("speed", 1.0)),
                                     "volume": current_prefs.volume if current_prefs else 100})
            except WebSocketDisconnect:
                return

        async def writer():
            while True:
                item = await queue.get()
                if item is None:
                    return
                try:
                    await websocket.send_json(_status_payload(item, "start"))
                    alert_type = item.get("alert_type", "tts")
                    if alert_type in {"system_sound", "custom_audio"}:
                        await websocket.send_json(_status_payload(item, "play"))
                    elif item.get("provider") == "fish":
                        if user.plan.lower() != "pro":
                            raise PermissionError("Fish Audio is available on the Pro plan.")
                        async for chunk in stream_tts(item["text"], reference_id=item.get("fish_voice_id") or item.get("voice"),
                                                      model=item.get("fish_model") or settings.FISH_AUDIO_PRO_MODEL,
                                                      speed=item.get("speed", 1.0)):
                            await websocket.send_bytes(chunk)
                    elif item.get("provider") == "edge":
                        async for chunk in tts_streaming_generator(item["text"], item["voice"], item.get("pitch", "+0Hz")):
                            await websocket.send_bytes(chunk)
                    else:
                        raise ValueError("Unsupported TTS provider.")
                    await websocket.send_json(_status_payload(item, "end"))
                except (FishAudioError, PermissionError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "id": item.get("id"), "detail": str(exc)})
                except Exception as exc:
                    await websocket.send_json({"type": "error", "id": item.get("id"), "detail": str(exc)})

        reader_task = asyncio.create_task(reader())
        writer_task = asyncio.create_task(writer())
        done, pending = await asyncio.wait({reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        # The live session owns the queue. A WebSocket disconnect must not
        # remove it because TikTok can continue producing events and a later
        # WebSocket connection must be able to consume the same queue.
        pass
