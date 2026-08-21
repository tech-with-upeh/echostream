from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import DBUser, DBUserPreferences

router = APIRouter(tags=["Preferences"])

class PreferencesSchema(BaseModel):
    tiktok_username: str | None = None
    comment_prefix: str = ""
    comment_suffix: str = ""
    voice: str = "en-US-GuyNeural"
    pitch: str = "+0Hz"

    class Config:
        from_attributes = True

@router.get("/v1/preferences", response_model=PreferencesSchema)
def get_preferences(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == current_user.id).first()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs

@router.put("/v1/preferences", response_model=PreferencesSchema)
def update_preferences(
    payload: PreferencesSchema,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == current_user.id).first()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id)
        db.add(prefs)

    prefs.tiktok_username = payload.tiktok_username
    prefs.comment_prefix = payload.comment_prefix
    prefs.comment_suffix = payload.comment_suffix
    prefs.voice = payload.voice
    prefs.pitch = payload.pitch
    db.commit()
    db.refresh(prefs)
    return prefs
