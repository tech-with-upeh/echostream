from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import jwt
from jwt.exceptions import InvalidTokenError

from app.dependencies import get_db, get_current_user
from app.models import DBUser, DBRefreshToken
from app.schemas import UserRegisterSchema, UserLoginSchema, UserResponse, TokenResponse, RefreshRequestSchema, ResendEmailSchema
from app.config import settings
from app.security import get_password_hash, verify_password, create_access_token, create_refresh_token, create_verification_token
from app.email_service import send_verification_email

router = APIRouter(tags=["Authentication"])

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserRegisterSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing_user = db.query(DBUser).filter(DBUser.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    
    hashed_pwd = get_password_hash(user_data.password)
    new_user = DBUser(
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        email=user_data.email,
        hashed_password=hashed_pwd,
        is_verified=False  # Explicitly unverified on generation
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Fire off verification email asynchronously using FastAPI background tasks
    v_token = create_verification_token(email=new_user.email)
    background_tasks.add_task(send_verification_email, new_user.email, v_token)
    
    return new_user


@router.post("/login", response_model=TokenResponse)
def login(login_data: UserLoginSchema, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == login_data.email).first()
    
    if not db_user or not verify_password(login_data.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
        
    # Enforce email verification constraint
    if not db_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your email address has not been verified. Please check your inbox."
        )
    
    access_token = create_access_token(user_id=db_user.id)
    refresh_token_str, expires_at = create_refresh_token(user_id=db_user.id)
    
    db_refresh_token = DBRefreshToken(token=refresh_token_str, user_id=db_user.id, expires_at=expires_at)
    db.add(db_refresh_token)
    db.commit()
    
    return {"access_token": access_token, "refresh_token": refresh_token_str}


@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "verification":
            raise HTTPException(status_code=400, detail="Invalid token scope")
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="Verification link has expired or is invalid.")
        
    db_user = db.query(DBUser).filter(DBUser.email == email).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if db_user.is_verified:
        return {"message": "Email is already verified."}
        
    db_user.is_verified = True
    db.commit()
    return {"message": "Email address successfully verified!"}


@router.post("/resend-verification")
async def resend_verification(payload: ResendEmailSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == payload.email).first()
    
    # Generic success message response patterns prevent email harvesting attacks
    if not db_user:
        return {"message": "If the account exists, a new verification link has been sent."}
        
    if db_user.is_verified:
        raise HTTPException(status_code=400, detail="This account is already verified.")
        
    new_v_token = create_verification_token(email=db_user.email)
    background_tasks.add_task(send_verification_email, db_user.email, new_v_token)
    
    return {"message": "If the account exists, a new verification link has been sent."}
