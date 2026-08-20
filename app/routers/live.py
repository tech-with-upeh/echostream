from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.models import DBUser
from app.tiktok_manager import start_tiktok_session, stop_tiktok_session

router = APIRouter(tags=["Live Sessions"])

class StartLiveSchema(BaseModel):
    tiktok_username: str

@router.post("/v1/live/start")
async def go_live(payload: StartLiveSchema, current_user: DBUser = Depends(get_current_user)):
    await start_tiktok_session(current_user.id, payload.tiktok_username)
    return {"message": f"Listening to @{payload.tiktok_username}'s live comments."}

@router.post("/v1/live/stop")
async def stop_live(current_user: DBUser = Depends(get_current_user)):
    await stop_tiktok_session(current_user.id)
    return {"message": "Stopped listening."}
