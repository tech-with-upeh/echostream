import asyncio
from typing import Dict
from sqlalchemy.orm import Session
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, DisconnectEvent

from app.database import SessionLocal
from app.models import DBUserPreferences

active_sessions: Dict[int, asyncio.Queue] = {}
active_tiktok_clients: Dict[int, TikTokLiveClient] = {}


def _load_preferences(user_id: int) -> DBUserPreferences:
    db: Session = SessionLocal()
    try:
        prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == user_id).first()
        if prefs is None:
            prefs = DBUserPreferences(user_id=user_id)  # in-memory default, not saved
        return prefs
    finally:
        db.close()


def _apply_template(template: str, username: str) -> str:
    return template.replace("{username}", username)


async def start_tiktok_session(user_id: int, tiktok_username: str) -> None:
    if user_id in active_tiktok_clients:
        return

    prefs = _load_preferences(user_id)
    client = TikTokLiveClient(unique_id=tiktok_username)

    @client.on(CommentEvent)
    async def on_comment(event: CommentEvent):
        queue = active_sessions.get(user_id)
        if queue is None:
            return
        msg_id = str(event.common.msg_id) if event.common else str(id(event))
        username = event.user.nickname if event.user else "someone"
        prefix = _apply_template(prefs.comment_prefix or "", username)
        suffix = _apply_template(prefs.comment_suffix or "", username)
        spoken_text = f"{prefix}{event.comment}{suffix}"
        await queue.put({
            "id": msg_id,
            "event_type": "comment",
            "text": spoken_text,
            "voice": prefs.voice,
            "pitch": prefs.pitch,
        })

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
                await queue.put({
                    "id": "tiktok-connect-error",
                    "event_type": "error",
                    "text": "",
                    "voice": "en-US-GuyNeural",
                })

    active_tiktok_clients[user_id] = client
    asyncio.create_task(_run())


async def stop_tiktok_session(user_id: int) -> None:
    client = active_tiktok_clients.pop(user_id, None)
    if client is not None:
        await client.disconnect()
