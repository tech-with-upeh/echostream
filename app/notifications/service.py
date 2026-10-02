import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import DBNotification, DBNotificationDevice, DBNotificationPreference, DBUser
from app.notifications.providers.expo import send_expo_push
from app.redis_store import get_redis

logger = logging.getLogger(__name__)

_IDEMPOTENCY_TTL_SECONDS = 10 * 24 * 60 * 60  # 10 days, comfortably longer than any window
_CHECK_INTERVAL_SECONDS = 15 * 60


@dataclass
class _ExpiryReminder:
    key: str  # short slug used in the idempotency key and notification type
    days_before: float
    window_half_width_days: float  # window is [days_before - half, days_before + half]
    title: str
    body: str


_EXPIRY_REMINDERS = [
    _ExpiryReminder(
        key="7-days",
        days_before=7,
        window_half_width_days=0.5,
        title="Subscription expiring soon",
        body="Your Pro subscription expires in 7 days.",
    ),
    _ExpiryReminder(
        key="3-days",
        days_before=3,
        window_half_width_days=0.5,
        title="Subscription expiring soon",
        body="Your Pro subscription expires in 3 days.",
    ),
    _ExpiryReminder(
        key="1-day",
        days_before=1,
        window_half_width_days=0.25,
        title="Subscription expiring tomorrow",
        body="Your Pro subscription expires tomorrow.",
    ),
]


# Maps a notification `type` string to the preference column that gates it.
# Types not listed here (e.g. "test") always send. account_security is listed
# with None so it's always sent too, regardless of push_enabled's sibling
# category toggles — remove the None special-case if you'd rather let users
# mute security notifications as well.
_TYPE_TO_PREFERENCE_FIELD: dict[str, str | None] = {
    "subscription_expiring_7_days": "subscription_enabled",
    "subscription_expiring_3_days": "subscription_enabled",
    "subscription_expiring_1_day": "subscription_enabled",
    "subscription_expired": "subscription_enabled",
    "streaming_reminder": "streaming_reminders_enabled",
    "product_update": "product_updates_enabled",
    "account_security": None,
}


class NotificationService:
    async def get_or_create_preferences(
        self, db: AsyncSession, user_id: int
    ) -> DBNotificationPreference:
        result = await db.execute(
            select(DBNotificationPreference).where(
                DBNotificationPreference.user_id == user_id
            )
        )
        prefs = result.scalar_one_or_none()
        if prefs is not None:
            return prefs

        now_utc = datetime.now(timezone.utc)
        prefs = DBNotificationPreference(
            user_id=user_id,
            created_at=now_utc,
            updated_at=now_utc,
        )
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
        return prefs

    async def _should_send(self, db: AsyncSession, user_id: int, type: str) -> bool:
        prefs = await self.get_or_create_preferences(db, user_id)
        if not prefs.push_enabled:
            return False

        field = _TYPE_TO_PREFERENCE_FIELD.get(type)
        if field is None:
            return True  # unmapped types (e.g. "test") and account_security always send

        return bool(getattr(prefs, field))

    async def send(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        type: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DBNotification | None:
        if not await self._should_send(db, user_id, type):
            logger.info(
                "Skipping send for user_id=%s type=%s: disabled by preferences",
                user_id, type,
            )
            return None

        now_utc = datetime.now(timezone.utc)

        notification = DBNotification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            data=json.dumps(data) if data else None,
            created_at=now_utc,
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)

        result = await db.execute(
            select(DBNotificationDevice).where(
                DBNotificationDevice.user_id == user_id,
                DBNotificationDevice.is_active.is_(True),
            )
        )
        devices = result.scalars().all()

        if not devices:
            logger.info("No active devices for user_id=%s, type=%s", user_id, type)
            return notification

        tokens = [d.push_token for d in devices]
        push_results = await send_expo_push(tokens, title, body, data)

        for device, push_result in zip(devices, push_results):
            if push_result.ok:
                continue
            logger.warning(
                "Push failed for user_id=%s push_token=%s error=%s message=%s",
                user_id, device.push_token, push_result.error_code, push_result.message,
            )
            if push_result.error_code == "DeviceNotRegistered":
                device.is_active = False
                device.updated_at = now_utc

        await db.commit()
        return notification

    async def _claim_idempotency_key(self, key: str) -> bool:
        """Atomically claim a dedup key. Returns True if this call is the
        first to claim it (i.e. the notification should proceed)."""
        claimed = await get_redis().set(key, "1", nx=True, ex=_IDEMPOTENCY_TTL_SECONDS)
        return bool(claimed)

    async def check_subscription_expiry_reminders(self, db: AsyncSession) -> int:
        """Covers the 7-day, 3-day and 1-day expiry reminders. Each reminder
        fires exactly once per user per subscription_ends_at value (keying on
        the exact timestamp means a renewal, which changes
        subscription_ends_at, naturally resets all reminders for the new
        period).

        Safe to call every 15 minutes.
        """
        now_utc = datetime.now(timezone.utc)
        sent_count = 0

        for reminder in _EXPIRY_REMINDERS:
            window_start = now_utc + timedelta(
                days=reminder.days_before - reminder.window_half_width_days
            )
            window_end = now_utc + timedelta(
                days=reminder.days_before + reminder.window_half_width_days
            )

            result = await db.execute(
                select(DBUser).where(
                    DBUser.subscription_status == "active",
                    DBUser.subscription_ends_at.isnot(None),
                    DBUser.subscription_ends_at >= window_start,
                    DBUser.subscription_ends_at <= window_end,
                )
            )
            users = result.scalars().all()

            for user in users:
                ends_at_iso = user.subscription_ends_at.replace(
                    tzinfo=timezone.utc
                ).isoformat()
                idempotency_key = (
                    f"notif:subscription-expiring:{reminder.key}:{user.id}:{ends_at_iso}"
                )
                if not await self._claim_idempotency_key(idempotency_key):
                    continue

                await self.send(
                    db,
                    user_id=user.id,
                    type=f"subscription_expiring_{reminder.key.replace('-', '_')}",
                    title=reminder.title,
                    body=reminder.body,
                    data={"screen": "subscription"},
                )
                sent_count += 1

            logger.info(
                "check_subscription_expiry_reminders[%s]: %s candidate(s)",
                reminder.key, len(users),
            )

        return sent_count

    async def check_subscription_expired(self, db: AsyncSession) -> int:
        """Finds users whose subscription has already passed its end date
        and sends a one-time 'expired' notification per subscription_ends_at
        value. Does not change subscription_status itself — that's handled
        by require_active_subscription when the user next hits a gated
        endpoint. This only notifies.

        Safe to call every 15 minutes.
        """
        now_utc = datetime.now(timezone.utc)

        result = await db.execute(
            select(DBUser).where(
                DBUser.subscription_status == "active",
                DBUser.subscription_ends_at.isnot(None),
                DBUser.subscription_ends_at < now_utc,
            )
        )
        users = result.scalars().all()

        sent_count = 0
        for user in users:
            ends_at_iso = user.subscription_ends_at.replace(tzinfo=timezone.utc).isoformat()
            idempotency_key = f"notif:subscription-expired:{user.id}:{ends_at_iso}"
            if not await self._claim_idempotency_key(idempotency_key):
                continue

            await self.send(
                db,
                user_id=user.id,
                type="subscription_expired",
                title="Subscription expired",
                body="Your Pro subscription has expired. Renew to keep access.",
                data={"screen": "subscription"},
            )
            sent_count += 1

        logger.info(
            "check_subscription_expired: %s candidate(s), %s sent",
            len(users), sent_count,
        )
        return sent_count


notification_service = NotificationService()


async def notification_scheduler(stop_event: asyncio.Event) -> None:
    """Runs every 15 minutes: expiry reminders + expired check, matching the
    gift_catalog_scheduler pattern in app/gift_catalog.py."""
    while not stop_event.is_set():
        try:
            async with AsyncSessionLocal() as db:
                await notification_service.check_subscription_expiry_reminders(db)
                await notification_service.check_subscription_expired(db)
        except Exception:
            logger.exception("notification_scheduler: check failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_CHECK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass