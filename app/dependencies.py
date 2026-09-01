from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DBUser, DBUserSession

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

async def get_db():
    async with AsyncSessionLocal() as db:
        yield db

async def get_current_token_payload(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access" or not payload.get("sub") or not payload.get("session_id"):
            raise credentials_exception
        int(payload["sub"])
    except (InvalidTokenError, ValueError, TypeError):
        raise credentials_exception
    return payload

async def get_current_user(payload: dict = Depends(get_current_token_payload), db: AsyncSession = Depends(get_db)) -> DBUser:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    user_id = int(payload["sub"])
    session_id = payload["session_id"]
    result = await db.execute(
        select(DBUser)
        .join(DBUserSession, DBUserSession.user_id == DBUser.id)
        .where(
            DBUser.id == user_id,
            DBUserSession.id == session_id,
            DBUserSession.revoked_at.is_(None),
        )
    )
    db_user = result.scalar_one_or_none()
    if db_user is None or not db_user.is_active:
        raise credentials_exception
    return db_user

async def require_admin(current_user: DBUser = Depends(get_current_user)) -> DBUser:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required.")
    return current_user

async def require_active_subscription(current_user: DBUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> DBUser:
    now_utc = datetime.now(timezone.utc)
    if current_user.subscription_status == "free_trial":
        if current_user.trial_ends_at and current_user.trial_ends_at.replace(tzinfo=timezone.utc) < now_utc:
            current_user.subscription_status = "expired"
            await db.commit()
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Your free trial has expired. Please upgrade to a premium plan to continue.")
    elif current_user.subscription_status == "active":
        if current_user.subscription_ends_at and current_user.subscription_ends_at.replace(tzinfo=timezone.utc) < now_utc:
            current_user.subscription_status = "expired"
            await db.commit()
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Your subscription plan has expired or billing failed. Please update your payment details.")
    elif current_user.subscription_status in ["expired", "canceled"]:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Active premium subscription required.")
    return current_user

async def require_pro_subscription(current_user: DBUser = Depends(require_active_subscription)) -> DBUser:
    if current_user.plan.lower() != "pro":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Fish Audio is available on the Pro plan.")
    return current_user
