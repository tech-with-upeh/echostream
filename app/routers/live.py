from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.live_runtime import acquire_live_owner, get_live_status, request_stop, set_live_state, stop_runtime_session
from app.models import DBUser, DBUserPreferences
from app.tiktok_manager import active_tiktok_clients, start_tiktok_session, stop_tiktok_session

router = APIRouter(tags=["Live Sessions"])


async def _get_preferences(user_id: int, db: AsyncSession) -> DBUserPreferences | None:
    result = await db.execute(select(DBUserPreferences).where(DBUserPreferences.user_id == user_id))
    return result.scalar_one_or_none()


@router.post("/v1/live/start")
async def go_live(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    prefs = await _get_preferences(current_user.id, db)
    tiktok_username = (prefs.tiktok_username or "").strip() if prefs else ""
    if not tiktok_username:
        raise HTTPException(status_code=422, detail="Set your TikTok username in preferences before starting a live session.")

    existing = await get_live_status(current_user.id, username=tiktok_username)
    if existing["status"] in {"connecting", "ready", "stopping"}:
        return {"message": f"Already listening to @{tiktok_username}.", **existing}

    if not await acquire_live_owner(current_user.id):
        existing = await get_live_status(current_user.id, username=tiktok_username)
        return {"message": f"A live session for @{tiktok_username} is already running.", **existing}

    await set_live_state(current_user.id, "connecting", username=tiktok_username)
    await start_tiktok_session(current_user.id, tiktok_username)
    return {"message": f"Connecting to @{tiktok_username}.", **await get_live_status(current_user.id, username=tiktok_username)}


@router.post("/v1/live/stop")
async def stop_live(current_user: DBUser = Depends(get_current_user)):
    await set_live_state(current_user.id, "stopping")
    if current_user.id in active_tiktok_clients:
        await stop_tiktok_session(current_user.id)
        await stop_runtime_session(current_user.id)
        return {"message": "Stopped listening.", "status": "stopped"}

    owner = await request_stop(current_user.id)
    if owner:
        return {"message": "Stop requested.", "status": "stopping"}

    await stop_runtime_session(current_user.id)
    return {"message": "Stopped listening.", "status": "stopped"}


@router.get("/v1/live/status")
async def live_status(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    prefs = await _get_preferences(current_user.id, db)
    username = (prefs.tiktok_username or "").strip() if prefs else None
    return await get_live_status(current_user.id, username=username)
