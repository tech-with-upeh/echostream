from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import DBUser
from datetime import datetime, timezone

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> DBUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        # Block refresh tokens from accidentally accessing standard data endpoints
        if user_id is None or token_type != "access":
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception
        
    db_user = db.query(DBUser).filter(DBUser.id == int(user_id)).first()
    if db_user is None:
        raise credentials_exception
    return db_user

def require_active_subscription(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)) -> DBUser:
    """
    Protect premium routes. Checks if user trial or paid subscription is still valid.
    Automatically updates expired accounts in real-time.
    """
    now_utc = datetime.now(timezone.utc)
    
    # 1. Evaluate Free Trial accounts
    if current_user.subscription_status == "free_trial":
        # If the trial deadline has passed
        if current_user.trial_ends_at.replace(tzinfo=timezone.utc) < now_utc:
            current_user.subscription_status = "expired"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Your free trial has expired. Please upgrade to a premium plan to continue."
            )
            
    # 2. Evaluate Paid Subscription accounts
    elif current_user.subscription_status == "active":
        if current_user.subscription_ends_at and current_user.subscription_ends_at.replace(tzinfo=timezone.utc) < now_utc:
            current_user.subscription_status = "expired"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Your subscription plan has expired or billing failed. Please update your payment details."
            )
            
    # 3. Block accounts that are explicitly marked expired or canceled
    elif current_user.subscription_status in ["expired", "canceled"]:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Active premium subscription required."
        )
        
    return current_user
