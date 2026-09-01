import asyncio
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
import jwt
import secrets
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db, get_current_user, get_current_token_payload
from app.models import DBUser, DBUserSession, DBRefreshToken, DBEmailVerificationCode, DBResetPassVerificationCode
from app.schemas import UserRegisterSchema, UserResetPasswordSchema, UserForgotPasswordSchema, UserLoginSchema, UserResponse, TokenResponse, RefreshRequestSchema, VerifyEmailWithCodeSchema, ResendVerificationSchema, SocialAuthSchema
from app.config import settings
from app.security import get_password_hash, verify_password, create_session_id, create_access_token, create_refresh_token, create_verification_token, generate_numeric_otp
from app.email_service import send_combined_verification_email, send_combined_reset_pass_email
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

router = APIRouter(tags=["Authentication"])


async def _verify_google_token(id_token: str):
    return await asyncio.to_thread(
        google_id_token.verify_oauth2_token,
        id_token,
        google_requests.Request(),
        settings.GOOGLE_CLIENT_ID,
    )


async def _hash_password(password: str) -> str:
    return await asyncio.to_thread(get_password_hash, password)


async def _verify_password(password: str, hashed_password: str) -> bool:
    return await asyncio.to_thread(verify_password, password, hashed_password)


async def _issue_session_tokens(db: AsyncSession, user_id: int) -> tuple[str, str]:
    now_utc = datetime.now(timezone.utc)
    session_id = create_session_id()
    db.add(DBUserSession(
        id=session_id,
        user_id=user_id,
        created_at=now_utc,
        last_used_at=now_utc,
    ))
    access_token = create_access_token(user_id=user_id, session_id=session_id)
    refresh_token_str, expires_at = create_refresh_token(user_id=user_id, session_id=session_id)
    db.add(DBRefreshToken(
        token=refresh_token_str,
        user_id=user_id,
        session_id=session_id,
        expires_at=expires_at,
    ))
    return access_token, refresh_token_str


@router.post("/auth/google", response_model=TokenResponse)
async def google_auth(payload: SocialAuthSchema, db: AsyncSession = Depends(get_db)):
    try:
        id_info = await _verify_google_token(payload.id_token)
        email = id_info.get("email")
        first_name = id_info.get("given_name", "Social")
        last_name = id_info.get("family_name", "User")
        if not email:
            raise HTTPException(status_code=400, detail="Google token missing email scope.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired Google token.")

    result = await db.execute(select(DBUser).where(DBUser.email == email))
    db_user = result.scalar_one_or_none()
    if not db_user:
        hashed_password = await _hash_password(secrets.token_hex(16))
        db_user = DBUser(
            first_name=first_name,
            last_name=last_name,
            email=email,
            hashed_password=hashed_password,
            is_verified=True,
            plan="starter",
            subscription_status="active",
            trial_ends_at=None,
            subscription_ends_at=None,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)

    access_token, refresh_token_str = await _issue_session_tokens(db, db_user.id)
    await db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token_str}


@router.post("/login", response_model=TokenResponse)
async def login(login_data: UserLoginSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBUser).where(DBUser.email == login_data.email))
    db_user = result.scalar_one_or_none()
    if not db_user or not await _verify_password(login_data.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not db_user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your email address has not been verified. Please check your inbox.")
    access_token, refresh_token_str = await _issue_session_tokens(db, db_user.id)
    await db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token_str}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(payload: RefreshRequestSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBRefreshToken).where(DBRefreshToken.token == payload.refresh_token))
    db_token = result.scalar_one_or_none()
    if not db_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    now_utc = datetime.now(timezone.utc)
    if db_token.expires_at.replace(tzinfo=timezone.utc) < now_utc:
        await db.delete(db_token)
        await db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired, please log in again")
    try:
        jwt_payload = jwt.decode(payload.refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        if jwt_payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token scope")
        if jwt_payload.get("sub") != str(db_token.user_id):
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if jwt_payload.get("session_id") != db_token.session_id:
            raise HTTPException(status_code=401, detail="Invalid refresh token session")
    except InvalidTokenError:
        await db.delete(db_token)
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid or altered refresh token")

    session_result = await db.execute(select(DBUserSession).where(
        DBUserSession.id == db_token.session_id,
        DBUserSession.user_id == db_token.user_id,
        DBUserSession.revoked_at.is_(None),
    ))
    session = session_result.scalar_one_or_none()
    if session is None:
        await db.delete(db_token)
        await db.commit()
        raise HTTPException(status_code=401, detail="Session has been revoked")

    session.last_used_at = now_utc
    new_access_token = create_access_token(user_id=db_token.user_id, session_id=db_token.session_id)
    new_refresh_str, new_expiry = create_refresh_token(user_id=db_token.user_id, session_id=db_token.session_id)
    db_token.token = new_refresh_str
    db_token.expires_at = new_expiry
    await db.commit()
    return {"access_token": new_access_token, "refresh_token": new_refresh_str}


@router.post("/logout")
async def logout(
    token_payload: dict = Depends(get_current_token_payload),
    db: AsyncSession = Depends(get_db),
):
    session_id = token_payload["session_id"]
    user_id = int(token_payload["sub"])
    result = await db.execute(select(DBUserSession).where(
        DBUserSession.id == session_id,
        DBUserSession.user_id == user_id,
        DBUserSession.revoked_at.is_(None),
    ))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has already been revoked")
    session.revoked_at = datetime.now(timezone.utc)
    await db.execute(delete(DBRefreshToken).where(DBRefreshToken.session_id == session_id))
    await db.commit()
    return {"status": "success", "message": "Logged out successfully."}


@router.post("/register", response_model=UserResponse)
async def register(user_data: UserRegisterSchema, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBUser).where(DBUser.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    now_utc = datetime.now(timezone.utc)
    hashed_password = await _hash_password(user_data.password)
    new_user = DBUser(
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        email=user_data.email,
        hashed_password=hashed_password,
        is_active=True,
        is_verified=False,
        plan="starter",
        subscription_status="active",
        trial_ends_at=None,
        subscription_ends_at=None,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    v_token = create_verification_token(email=new_user.email)
    v_code = generate_numeric_otp(length=6)
    db.add(DBEmailVerificationCode(email=new_user.email, code=v_code, expires_at=now_utc + timedelta(hours=2)))
    await db.commit()
    background_tasks.add_task(send_combined_verification_email, new_user.email, v_token, v_code)
    return new_user


@router.post("/verify-email-code")
async def verify_email_with_code(payload: VerifyEmailWithCodeSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBEmailVerificationCode).where(DBEmailVerificationCode.email == payload.email, DBEmailVerificationCode.code == payload.code))
    db_record = result.scalar_one_or_none()
    if not db_record:
        raise HTTPException(status_code=400, detail="Invalid verification code or email details.")
    if db_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        await db.delete(db_record)
        await db.commit()
        raise HTTPException(status_code=400, detail="The verification code has expired. Please request a new one.")
    result = await db.execute(select(DBUser).where(DBUser.email == payload.email))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User profile not found.")
    if db_user.is_verified:
        await db.delete(db_record)
        await db.commit()
        return {"status": "failed", "message": "Email is already verified."}
    db_user.is_verified = True
    await db.delete(db_record)
    await db.commit()
    access_token, refresh_token_str = await _issue_session_tokens(db, db_user.id)
    await db.commit()
    return {"status": "success", "message": "Email address successfully verified via code!", "access_token": access_token, "refresh_token": refresh_token_str}


@router.post("/reset-pass-code")
async def reset_pass_with_code(reset_data: UserResetPasswordSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBResetPassVerificationCode).where(DBResetPassVerificationCode.email == reset_data.email, DBResetPassVerificationCode.code == reset_data.token))
    db_record = result.scalar_one_or_none()
    if not db_record:
        raise HTTPException(status_code=400, detail="Invalid verification code or email details.")
    if db_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        await db.delete(db_record)
        await db.commit()
        raise HTTPException(status_code=400, detail="The verification code has expired. Please request a new one.")
    result = await db.execute(select(DBUser).where(DBUser.email == reset_data.email))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User profile not found.")
    db_user.hashed_password = await _hash_password(reset_data.password)
    access_token, refresh_token_str = await _issue_session_tokens(db, db_user.id)
    await db.execute(delete(DBResetPassVerificationCode).where(DBResetPassVerificationCode.email == db_user.email))
    await db.commit()
    return {"status": "success", "message": "Password Changed successfully verified via Code!", "access_token": access_token, "refresh_token": refresh_token_str}


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")
        if email is None or token_type != "verification":
            raise HTTPException(status_code=400, detail="Invalid token scope")
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="Verification link has expired or is invalid.")
    result = await db.execute(select(DBUser).where(DBUser.email == email))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if db_user.is_verified:
        return {"status": "failed", "message": "Email is already verified."}
    db_user.is_verified = True
    await db.commit()
    access_token, refresh_token_str = await _issue_session_tokens(db, db_user.id)
    await db.commit()
    return {"status": "success", "message": "Email address successfully verified via Link!", "access_token": access_token, "refresh_token": refresh_token_str}


@router.post("/reset-password")
async def reset_pass(reset_data: UserResetPasswordSchema, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBResetPassVerificationCode).where(DBResetPassVerificationCode.email == reset_data.email, DBResetPassVerificationCode.token == reset_data.token))
    db_record = result.scalar_one_or_none()
    if not db_record:
        raise HTTPException(status_code=400, detail="Invalid Reset code or email details.")
    if db_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        await db.delete(db_record)
        await db.commit()
        raise HTTPException(status_code=400, detail="The Reset code has expired. Please request a new one.")
    try:
        payload = jwt.decode(reset_data.token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")
        if email is None or token_type != "verification":
            raise HTTPException(status_code=400, detail="Invalid token scope")
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="Verification link has expired or is invalid.")
    result = await db.execute(select(DBUser).where(DBUser.email == email))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db_user.hashed_password = await _hash_password(reset_data.password)
    access_token, refresh_token_str = await _issue_session_tokens(db, db_user.id)
    await db.execute(delete(DBResetPassVerificationCode).where(DBResetPassVerificationCode.email == db_user.email))
    await db.commit()
    return {"status": "success", "message": "Password CHanged successfully verified via Link!", "access_token": access_token, "refresh_token": refresh_token_str}


@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationSchema, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBUser).where(DBUser.email == payload.email))
    db_user = result.scalar_one_or_none()
    if not db_user:
        return {"status": "success", "message": "If the account exists, a new verification link and code have been sent."}
    if db_user.is_verified:
        raise HTTPException(status_code=400, detail="This account is already verified.")
    await db.execute(delete(DBEmailVerificationCode).where(DBEmailVerificationCode.email == db_user.email))
    new_v_token = create_verification_token(email=db_user.email)
    new_v_code = generate_numeric_otp(length=6)
    db.add(DBEmailVerificationCode(email=db_user.email, code=new_v_code, expires_at=datetime.now(timezone.utc) + timedelta(hours=2)))
    await db.commit()
    background_tasks.add_task(send_combined_verification_email, db_user.email, new_v_token, new_v_code)
    return {"status": "success", "message": "If the account exists, a new verification link and code have been sent."}


@router.post("/forgot-password")
async def reset_password(payload: UserForgotPasswordSchema, bg_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBUser).where(DBUser.email == payload.email))
    db_user = result.scalar_one_or_none()
    if not db_user:
        return {"status": "success", "message": "if the account exists, a reset password link and code have been sent"}
    await db.execute(delete(DBResetPassVerificationCode).where(DBResetPassVerificationCode.email == db_user.email))
    new_r_token = create_verification_token(email=db_user.email, ttl_in_hours=0.5)
    new_r_code = generate_numeric_otp(length=6)
    db.add(DBResetPassVerificationCode(email=db_user.email, code=new_r_code, token=new_r_token, expires_at=datetime.now(timezone.utc) + timedelta(minutes=30)))
    await db.commit()
    bg_tasks.add_task(send_combined_reset_pass_email, db_user.email, new_r_token, new_r_code)
    return {"status": "success", "message": "If the account exists, a Reset Password link and code have been sent"}


@router.get("/users/me", response_model=UserResponse)
async def read_users_me(current_user: DBUser = Depends(get_current_user)):
    return current_user
