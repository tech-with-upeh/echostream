from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import DBUser, DBUserPreferences
from app.schemas import PreferencesSchema

router = APIRouter(tags=["Preferences"])


def _get_or_create_preferences(current_user: DBUser, db: Session) -> DBUserPreferences:
    prefs = db.query(DBUserPreferences).filter(DBUserPreferences.user_id == current_user.id).first()
    if prefs is None:
        prefs = DBUserPreferences(user_id=current_user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


@router.get("/v1/preferences", response_model=PreferencesSchema)
def get_preferences(
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_or_create_preferences(current_user, db)


@router.put("/v1/preferences", response_model=PreferencesSchema)
def update_preferences(
    payload: PreferencesSchema,
    current_user: DBUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prefs = _get_or_create_preferences(current_user, db)

    if payload.tts_provider == "fish" and current_user.plan.lower() != "pro":
        raise HTTPException(status_code=403, detail="Fish Audio is available on the Pro plan.")

    prefs.tiktok_username = payload.tiktok_username
    prefs.comment_prefix = payload.comment_prefix
    prefs.comment_suffix = payload.comment_suffix
    prefs.tts_provider = payload.tts_provider
    prefs.voice = payload.voice
    prefs.fish_voice_id = payload.fish_voice_id
    prefs.pitch = payload.pitch
    db.commit()
    db.refresh(prefs)
    return prefs
