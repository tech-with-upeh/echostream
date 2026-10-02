from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_admin
from app.models import DBNotificationDevice, DBUser
from app.notifications.service import notification_service
from app.schemas import (
    DeviceRegisterSchema,
    NotificationDeviceResponse,
    NotificationPreferencesResponse,
    NotificationPreferencesUpdateSchema,
    TestNotificationSchema,
)

router = APIRouter(tags=["Notifications"])


@router.post("/notifications/devices", response_model=NotificationDeviceResponse)
async def register_device(
    payload: DeviceRegisterSchema,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now_utc = datetime.now(timezone.utc)
    result = await db.execute(
        select(DBNotificationDevice).where(
            DBNotificationDevice.push_token == payload.push_token
        )
    )
    device = result.scalar_one_or_none()

    if device is None:
        device = DBNotificationDevice(
            user_id=current_user.id,
            push_token=payload.push_token,
            platform=payload.platform,
            is_active=True,
            app_version=payload.app_version,
            last_seen_at=now_utc,
            created_at=now_utc,
            updated_at=now_utc,
        )
        db.add(device)
    else:
        # Same physical device token, possibly a reinstall or a different
        # account signing in on this device. Reassign to the current user.
        device.user_id = current_user.id
        device.platform = payload.platform
        device.is_active = True
        device.app_version = payload.app_version
        device.last_seen_at = now_utc
        device.updated_at = now_utc

    await db.commit()
    await db.refresh(device)
    return device

@router.get("/notifications/preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.get_or_create_preferences(db, current_user.id)


@router.put("/notifications/preferences", response_model=NotificationPreferencesResponse)
async def update_notification_preferences(
    payload: NotificationPreferencesUpdateSchema,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    prefs = await notification_service.get_or_create_preferences(db, current_user.id)

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(prefs, field, value)
    prefs.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(prefs)
    return prefs

@router.post("/notifications/test")
async def send_test_notification(
    payload: TestNotificationSchema,
    current_admin: DBUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only manual trigger. Always sends to the calling admin's own
    devices — never to an arbitrary user_id — so this can't be used to spam
    other users' phones."""
    notification = await notification_service.send(
        db,
        user_id=current_admin.id,
        type="test",
        title=payload.title,
        body=payload.body,
    )
    if notification == None:
        return {"status": "failed"}
    return {"status": "sent", "notification_id": notification.id}