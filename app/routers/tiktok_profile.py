from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models import DBUser, DBUserPreferences
from app.r2_storage import R2StorageError, delete_tiktok_image, upload_tiktok_image
from app.tiktok_image import TikTokImageError, fetch_tiktok_profile_image


router = APIRouter(tags=["TikTok Profile"])


async def _get_tiktok_username(
    current_user: DBUser,
    db: AsyncSession,
) -> str:
    result = await db.execute(
        select(DBUserPreferences.tiktok_username).where(
            DBUserPreferences.user_id == current_user.id
        )
    )
    username = result.scalar_one_or_none()

    if not username:
        raise HTTPException(
            status_code=400,
            detail="Set your TikTok username before fetching your TikTok image.",
        )

    return username


async def _fetch_and_store_tiktok_image(
    *,
    current_user: DBUser,
    username: str,
    db: AsyncSession,
    old_image_url: str | None = None,
) -> str:
    try:
        image_bytes = await fetch_tiktok_profile_image(username)
        new_image_url = await upload_tiktok_image(
            image_bytes,
            user_id=current_user.id,
        )
    except TikTokImageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except R2StorageError as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to store the TikTok profile image.",
        ) from exc

    current_user.tt_image = new_image_url

    try:
        await db.commit()
        await db.refresh(current_user)
    except Exception:
        await db.rollback()
        try:
            await delete_tiktok_image(
                new_image_url,
                user_id=current_user.id,
            )
        except R2StorageError:
            pass
        raise

    if old_image_url and old_image_url != new_image_url:
        try:
            await delete_tiktok_image(
                old_image_url,
                user_id=current_user.id,
            )
        except R2StorageError:
            # The database already points at the new image. A stale old
            # object is harmless and can be cleaned up later.
            pass

    return new_image_url


@router.get("/v1/users/tt-image")
async def get_tiktok_image(
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.tt_image:
        return {"tt_image": current_user.tt_image}

    username = await _get_tiktok_username(current_user, db)
    image_url = await _fetch_and_store_tiktok_image(
        current_user=current_user,
        username=username,
        db=db,
    )

    return {"tt_image": image_url}


@router.post("/v1/users/tt-image/refresh")
async def refresh_tiktok_image(
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    username = await _get_tiktok_username(current_user, db)
    old_image_url = current_user.tt_image

    image_url = await _fetch_and_store_tiktok_image(
        current_user=current_user,
        username=username,
        db=db,
        old_image_url=old_image_url,
    )

    return {"tt_image": image_url}
