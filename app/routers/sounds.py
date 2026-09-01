from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models import DBAudioAsset, DBUser
from app.r2_storage import R2StorageError, delete_audio_key, upload_audio
from app.schemas import AudioAssetResponse

router = APIRouter(tags=["Audio Sounds"])
_MAX_AUDIO_SIZE = 10 * 1024 * 1024

async def _upload_asset(file: UploadFile, name: str, owner_user_id: int | None, db: AsyncSession):
    contents = await file.read()
    await file.close()
    if len(contents) > _MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="Audio file must be 10 MB or smaller.")
    clean_name = (name or Path(file.filename or "sound").stem).strip()[:255] or "sound"
    try:
        key, url = await upload_audio(contents, owner_user_id=owner_user_id, name=clean_name)
    except R2StorageError as exc:
        code = 400 if str(exc).startswith("Unsupported audio format") or str(exc) == "Audio file is empty." else 502
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)
    asset = DBAudioAsset(name=clean_name, r2_key=key, public_url=url, owner_user_id=owner_user_id, created_at=now, updated_at=now)
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset

@router.get("/v1/sounds", response_model=list[AudioAssetResponse])
async def list_user_sounds(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.owner_user_id == current_user.id).order_by(DBAudioAsset.created_at.desc()))
    return result.scalars().all()

@router.get("/v1/sounds/{sound_id}", response_model=AudioAssetResponse)
async def get_user_sound(sound_id: int, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.id == sound_id, DBAudioAsset.owner_user_id == current_user.id))
    asset = result.scalar_one_or_none()
    if asset is None: raise HTTPException(status_code=404, detail="Sound not found.")
    return asset

@router.delete("/v1/sounds/{sound_id}")
async def delete_user_sound(sound_id: int, current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.id == sound_id, DBAudioAsset.owner_user_id == current_user.id))
    asset = result.scalar_one_or_none()
    if asset is None: raise HTTPException(status_code=404, detail="Sound not found.")
    key = asset.r2_key
    await db.delete(asset)
    await db.commit()
    try: await delete_audio_key(key)
    except R2StorageError: pass
    return {"message": "Sound deleted successfully."}

@router.get("/v1/system-sounds", response_model=list[AudioAssetResponse])
async def list_system_sounds(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.owner_user_id.is_(None)).order_by(DBAudioAsset.name.asc()))
    return result.scalars().all()

@router.post("/v1/admin/sounds", response_model=AudioAssetResponse)
async def upload_system_sound(name: str = Form(...), file: UploadFile = File(...), current_admin: DBUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    return await _upload_asset(file, name, None, db)

@router.delete("/v1/admin/sounds/{sound_id}")
async def delete_system_sound(sound_id: int, current_admin: DBUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBAudioAsset).where(DBAudioAsset.id == sound_id, DBAudioAsset.owner_user_id.is_(None)))
    asset = result.scalar_one_or_none()
    if asset is None: raise HTTPException(status_code=404, detail="System sound not found.")
    key = asset.r2_key
    await db.delete(asset)
    await db.commit()
    try: await delete_audio_key(key)
    except R2StorageError: pass
    return {"message": "System sound deleted successfully."}
