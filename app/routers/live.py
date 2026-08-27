import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.models import DBUser
from app.tiktok_manager import active_sessions, start_tiktok_session, stop_tiktok_session

router = APIRouter(tags=["Live Sessions"])


class StartLiveSchema(BaseModel):
    tiktok_username: str


@router.post("/v1/live/start")
async def go_live(payload: StartLiveSchema, current_user: DBUser = Depends(get_current_user)):
    # The live endpoint owns the TikTok session lifecycle. Create the event
    # queue here so TikTok events have a destination even before the WebSocket
    # connects. The WebSocket attaches to this same queue later.
    active_sessions.setdefault(current_user.id, asyncio.Queue())
    await start_tiktok_session(current_user.id, payload.tiktok_username)
    return {
        "message": f"Listening to @{payload.tiktok_username}'s live comments.",
        "tiktok_username": payload.tiktok_username,
        "status": "started",
    }


@router.post("/v1/live/stop")
async def stop_live(current_user: DBUser = Depends(get_current_user)):
    await stop_tiktok_session(current_user.id)
    active_sessions.pop(current_user.id, None)
    return {"message": "Stopped listening.", "status": "stopped"}
