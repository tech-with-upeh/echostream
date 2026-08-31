from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DBUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

async def get_db():
    async with AsyncSessionLocal() as db:
        yield db

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> DBUser:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            raise credentials_exception
        user_id = int(user_id)
    except (InvalidTokenError, ValueError, TypeError):
        raise credentials_exception
    result = await db.execute(select(DBUser).where(DBUser.id == user_id))
    db_user = result.scalar_one_or_none()
    if db_user is None:
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
