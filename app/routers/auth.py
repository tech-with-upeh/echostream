import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import jwt
import secrets
from jwt.exceptions import InvalidTokenError
from app.dependencies import get_db, get_current_user
from app.models import DBUser, DBRefreshToken, DBEmailVerificationCode
from app.schemas import UserRegisterSchema, UserLoginSchema, UserResponse, TokenResponse, RefreshRequestSchema, VerifyEmailWithCodeSchema, ResendVerificationSchema, SocialAuthSchema
from app.config import settings
from app.security import get_password_hash, verify_password, create_access_token, create_refresh_token, create_verification_token, generate_numeric_otp
from app.email_service import send_combined_verification_email
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

router = APIRouter(tags=["Authentication"])
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "://googleusercontent.com")

@router.post("/auth/google", response_model=TokenResponse)
def google_auth(payload: SocialAuthSchema, db: Session = Depends(get_db)):
    try:
        id_info = google_id_token.verify_oauth2_token(payload.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        email = id_info.get("email")
        first_name = id_info.get("given_name", "Social")
        last_name = id_info.get("family_name", "User")
        if not email:
            raise HTTPException(status_code=400, detail="Google token missing email scope.")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired Google token.")
    db_user = db.query(DBUser).filter(DBUser.email == email).first()
    if not db_user:
        db_user = DBUser(first_name=first_name, last_name=last_name, email=email, hashed_password=get_password_hash(secrets.token_hex(16)), is_verified=True, plan="starter", subscription_status="active", trial_ends_at=None, subscription_ends_at=None)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
    access_token = create_access_token(user_id=db_user.id)
    refresh_token_str, expires_at = create_refresh_token(user_id=db_user.id)
    db.add(DBRefreshToken(token=refresh_token_str, user_id=db_user.id, expires_at=expires_at))
    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token_str}

@router.post("/login", response_model=TokenResponse)
def login(login_data: UserLoginSchema, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == login_data.email).first()
    if not db_user or not verify_password(login_data.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not db_user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your email address has not been verified. Please check your inbox.")
    access_token = create_access_token(user_id=db_user.id)
    refresh_token_str, expires_at = create_refresh_token(user_id=db_user.id)
    db.add(DBRefreshToken(token=refresh_token_str, user_id=db_user.id, expires_at=expires_at))
    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token_str}

@router.post("/refresh", response_model=TokenResponse)
def refresh_session(payload: RefreshRequestSchema, db: Session = Depends(get_db)):
    db_token = db.query(DBRefreshToken).filter(DBRefreshToken.token == payload.refresh_token).first()
    if not db_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if db_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(db_token); db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired, please log in again")
    try:
        jwt_payload = jwt.decode(payload.refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        if jwt_payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token scope")
    except InvalidTokenError:
        db.delete(db_token); db.commit()
        raise HTTPException(status_code=401, detail="Invalid or altered refresh token")
    user_id = db_token.user_id
    db.delete(db_token); db.commit()
    new_access_token = create_access_token(user_id=user_id)
    new_refresh_str, new_expiry = create_refresh_token(user_id=user_id)
    db.add(DBRefreshToken(token=new_refresh_str, user_id=user_id, expires_at=new_expiry)); db.commit()
    return {"access_token": new_access_token, "refresh_token": new_refresh_str}

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserRegisterSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing_user = db.query(DBUser).filter(DBUser.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    now_utc = datetime.now(timezone.utc)
    trial_duration = timedelta(days=14)
    trial_expiration = now_utc + trial_duration

    hashed_pwd = get_password_hash(user_data.password)
    new_user = DBUser(
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        email=user_data.email,
        hashed_password=hashed_pwd,
        is_verified=False,
        plan="free",
        subscription_status="active",
    )   
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Send verification mail parameters asynchronously
    v_token = create_verification_token(email=new_user.email)
    v_code = generate_numeric_otp(length=6)
    db.add(DBEmailVerificationCode(email=new_user.email, code=v_code, expires_at=now_utc + timedelta(hours=2))); db.commit()
    background_tasks.add_task(send_combined_verification_email, new_user.email, v_token, v_code)
    return new_user

@router.post("/verify-email-code")
def verify_email_with_code(payload: VerifyEmailWithCodeSchema, db: Session = Depends(get_db)):
    db_record = db.query(DBEmailVerificationCode).filter(DBEmailVerificationCode.email == payload.email, DBEmailVerificationCode.code == payload.code).first()
    if not db_record:
        raise HTTPException(status_code=400, detail="Invalid verification code or email details.")
    if db_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(db_record); db.commit()
        raise HTTPException(status_code=400, detail="The verification code has expired. Please request a new one.")
    db_user = db.query(DBUser).filter(DBUser.email == payload.email).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User profile not found.")
    if db_user.is_verified:
        db.delete(db_record); db.commit(); return {"message": "Email is already verified."}
    db_user.is_verified = True; db.delete(db_record); db.commit()
    return {"message": "Email address successfully verified via code!"}

@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub"); token_type = payload.get("type")
        if email is None or token_type != "verification":
            raise HTTPException(status_code=400, detail="Invalid token scope")
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="Verification link has expired or is invalid.")
    db_user = db.query(DBUser).filter(DBUser.email == email).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if db_user.is_verified:
        return {"message": "Email is already verified."}
    db_user.is_verified = True; db.commit()
    return {"message": "Email address successfully verified via link!"}

@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == payload.email).first()
    if not db_user:
        return {"message": "If the account exists, a new verification link and code have been sent."}
    if db_user.is_verified:
        raise HTTPException(status_code=400, detail="This account is already verified.")
    db.query(DBEmailVerificationCode).filter(DBEmailVerificationCode.email == db_user.email).delete()
    new_v_token = create_verification_token(email=db_user.email)
    new_v_code = generate_numeric_otp(length=6)
    db.add(DBEmailVerificationCode(email=db_user.email, code=new_v_code, expires_at=datetime.now(timezone.utc) + timedelta(hours=2))); db.commit()
    background_tasks.add_task(send_combined_verification_email, db_user.email, new_v_token, new_v_code)
    return {"message": "If the account exists, a new verification link and code have been sent."}

@router.get("/users/me", response_model=UserResponse)
def read_users_me(current_user: DBUser = Depends(get_current_user)):
    return current_user
