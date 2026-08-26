import asyncio
import json

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.fish_audio import FishAudioError, stream_tts
from app.models import DBUser, DBUserPreferences
from app.routers.voice import tts_streaming_generator
from app.tiktok_manager import active_sessions, start_tiktok_session, stop_tiktok_session

router = APIRouter(tags=["Text-to-Speech (Live)"])


def _get_user_from_token(token: str, db: Session):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            return None
    except (InvalidTokenError, ValueError):
        return None
    return db.query(DBUser).filter(DBUser.id == int(user_id)).first()


def _status_payload(item: dict, event: str) -> dict:
    event_type = item.get("event_type", "comment")
    payload = {
        "type": "status",
        "id": item["id"],
        "event": event,
        "event_type": event_type,
    }
    if event_type == "comment":
        payload["comment"] = item["text"]
    return payload


@router.websocket("/ws/v1/tts")
async def live_tts_socket(websocket: WebSocket, token: str = Query(...)):
    db = SessionLocal()
    user: DBUser | None = None
    try:
        user = _get_user_from_token(token, db)
        if user is None:
            await websocket.close(code=4401)
            return

        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue()
        active_sessions[user.id] = queue

        prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == user.id).first()
        if prefs and prefs.tiktok_username:
            await start_tiktok_session(user.id, prefs.tiktok_username)

        async def reader():
            try:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        await websocket.send_json({"type": "error", "detail": "Invalid JSON."})
                        continue

                    if msg.get("type") != "speak":
                        await websocket.send_json({"type": "error", "detail": "Unknown message type."})
                        continue

                    text = (msg.get("text") or "").strip()
                    if not text:
                        await websocket.send_json({"type": "error", "id": msg.get("id"), "detail": "Text cannot be empty."})
                        continue

                    provider = (msg.get("provider") or (prefs.tts_provider if prefs else "edge")).lower()
                    voice = msg.get("voice") or (prefs.voice if prefs else "en-US-GuyNeural")
                    pitch = prefs.pitch if prefs else "+0Hz"
                    fish_voice_id = (prefs.fish_voice_id if prefs else None)

                    await queue.put({
                        "id": msg.get("id"),
                        "event_type": msg.get("event_type", "comment"),
                        "text": text,
                        "provider": provider,
                        "voice": voice,
                        "fish_voice_id": fish_voice_id,
                        "pitch": pitch,
                        "speed": float(msg.get("speed", 1.0)),
                    })
            except WebSocketDisconnect:
                await queue.put(None)

        async def writer():
            """Process one comment at a time so audio never overlaps."""
            while True:
                item = await queue.get()
                if item is None:
                    break
                try:
                    await websocket.send_json(_status_payload(item, "start"))
                    if item["provider"] == "fish":
                        if user.plan.lower() != "pro":
                            raise PermissionError("Fish Audio is available on the Pro plan.")
                        async for chunk in stream_tts(
                            item["text"],
                            reference_id=item.get("fish_voice_id") or item.get("voice"),
                            speed=item["speed"],
                        ):
                            await websocket.send_bytes(chunk)
                    elif item["provider"] == "edge":
                        async for chunk in tts_streaming_generator(
                            item["text"], item["voice"], item["pitch"]
                        ):
                            await websocket.send_bytes(chunk)
                    else:
                        raise ValueError("Unsupported TTS provider.")
                    await websocket.send_json(_status_payload(item, "end"))
                except (FishAudioError, PermissionError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "id": item["id"], "detail": str(exc)})
                except Exception as exc:
                    await websocket.send_json({"type": "error", "id": item["id"], "detail": str(exc)})

        reader_task = asyncio.create_task(reader())
        writer_task = asyncio.create_task(writer())
        done, pending = await asyncio.wait(
            {reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    finally:
        if user is not None:
            active_sessions.pop(user.id, None)
            await stop_tiktok_session(user.id)
        db.close()
