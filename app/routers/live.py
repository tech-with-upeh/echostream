import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_user
from app.models import DBUser, DBUserPreferences
from app.tiktok_manager import active_sessions, get_live_status, start_tiktok_session, stop_tiktok_session

router = APIRouter(tags=["Live Sessions"])


@router.post("/v1/live/start")
async def go_live(current_user: DBUser = Depends(get_current_user)):
    prefs = None
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == current_user.id).first()
        tiktok_username = (prefs.tiktok_username or "").strip() if prefs else ""
    finally:
        db.close()

    if not tiktok_username:
        raise HTTPException(status_code=422, detail="Set your TikTok username in preferences before starting a live session.")

    existing = get_live_status(current_user.id)
    if existing["status"] in {"connecting", "ready", "stopping"}:
        return {"message": f"Already listening to @{tiktok_username}.", "tiktok_username": tiktok_username, **existing}

    # The live endpoint owns the TikTok session lifecycle. The queue exists
    # before the TikTok client starts so events are not lost before a browser
    # WebSocket connects.
    active_sessions[current_user.id] = asyncio.Queue(maxsize=100)
    await start_tiktok_session(current_user.id, tiktok_username)
    return {"message": f"Listening to @{tiktok_username}.", "tiktok_username": tiktok_username, **get_live_status(current_user.id)}


@router.post("/v1/live/stop")
async def stop_live(current_user: DBUser = Depends(get_current_user)):
    await stop_tiktok_session(current_user.id)
    active_sessions.pop(current_user.id, None)
    return {"message": "Stopped listening.", "status": "stopped"}


@router.get("/v1/live/status")
async def live_status(current_user: DBUser = Depends(get_current_user)):
    return get_live_status(current_user.id)
