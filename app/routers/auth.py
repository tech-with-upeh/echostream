import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import jwt
import secrets
from jwt.exceptions import InvalidTokenError

from app.dependencies import get_db, get_current_user
from app.models import DBUser, DBRefreshToken, DBEmailVerificationCode
from app.schemas import UserRegisterSchema, UserLoginSchema, UserResponse, TokenResponse, RefreshRequestSchema, VerifyEmailWithCodeSchema, ResendVerificationSchema
from app.config import settings
from app.security import get_password_hash, verify_password, create_access_token, create_refresh_token, create_verification_token, generate_numeric_otp
from app.email_service import send_combined_verification_email

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from app.schemas import SocialAuthSchema


router = APIRouter(tags=["Authentication"])



GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "://googleusercontent.com")

@router.post("/auth/google", response_model=TokenResponse)
def google_auth(payload: SocialAuthSchema, db: Session = Depends(get_db)):
    try:
        # 1. Verify the integrity of the token directly against Google's public keys
        id_info = google_id_token.verify_oauth2_token(
            payload.id_token, 
            google_requests.Request(), 
            settings.GOOGLE_CLIENT_ID
        ) 

        # 2. Extract profile details safely from the verified payload
        email = id_info.get("email")
        first_name = id_info.get("given_name", "Social")
        last_name = id_info.get("family_name", "User")
        
        if not email:
            raise HTTPException(status_code=400, detail="Google token missing email scope.")

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Google token."
        )

    # 3. Check if this social user already exists in your Postgres database
    db_user = db.query(DBUser).filter(DBUser.email == email).first()

    if not db_user:
        # User doesn't exist yet -> Automatically register them on the fly!
        now_utc = datetime.now(timezone.utc)
        
        db_user = DBUser(
            first_name=first_name,
            last_name=last_name,
            email=email,
            # Generate a random string for password since they log in via Google
            hashed_password=get_password_hash(secrets.token_hex(16)),
            is_verified=True,  # Google already verified their email!
            subscription_status="free_trial",
            trial_ends_at=now_utc + timedelta(days=14)
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

    # 4. Mint and return your standard application Access + Refresh tokens
    access_token = create_access_token(user_id=db_user.id)
    refresh_token_str, expires_at = create_refresh_token(user_id=db_user.id)
    
    db_refresh_token = DBRefreshToken(token=refresh_token_str, user_id=db_user.id, expires_at=expires_at)
    db.add(db_refresh_token)
    db.commit()
    
    return {"access_token": access_token, "refresh_token": refresh_token_str}


@router.post("/login", response_model=TokenResponse)
def login(login_data: UserLoginSchema, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == login_data.email).first()
    
    if not db_user or not verify_password(login_data.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
        
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


# --- RESTORED: Token Refresh Endpoint ---
@router.post("/refresh", response_model=TokenResponse)
def refresh_session(payload: RefreshRequestSchema, db: Session = Depends(get_db)):
    # 1. Check if the refresh token exists in our Postgres database
    db_token = db.query(DBRefreshToken).filter(DBRefreshToken.token == payload.refresh_token).first()
    if not db_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
        
    # 2. Check if the database record shows it has expired
    if db_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(db_token)
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired, please log in again")

    # 3. Cryptographically verify the token structure itself via PyJWT
    try:
        jwt_payload = jwt.decode(payload.refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        if jwt_payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token scope")
    except InvalidTokenError:
        db.delete(db_token)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid or altered refresh token")

    db.delete(db_token) # Delete the old used token immediately
    db.commit()

    # 4. Generate a brand new access token
    new_access_token = create_access_token(user_id=db_token.user_id)
    
    # 5. Secure Token Rotation: Mint a brand new refresh token
    new_refresh_str, new_expiry = create_refresh_token(user_id=db_token.user_id)
    
    # 6. Swap out the old token for the new token in the database to prevent replay attacks
    db_token.token = new_refresh_str
    db_token.expires_at = new_expiry
    db.commit()

    return {"access_token": new_access_token, "refresh_token": new_refresh_str}

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserRegisterSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing_user = db.query(DBUser).filter(DBUser.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    
    # Calculate trial period dynamically (e.g., 14 days)
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
        
        # Assign free trial details automatically
        subscription_status="free_trial",
        trial_ends_at=trial_expiration
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Send verification mail parameters asynchronously
    v_token = create_verification_token(email=new_user.email)
    v_code = generate_numeric_otp(length=6)
    
    db_code = DBEmailVerificationCode(email=new_user.email, code=v_code, expires_at=now_utc + timedelta(hours=2))
    db.add(db_code)
    db.commit()
    
    background_tasks.add_task(send_combined_verification_email, new_user.email, v_token, v_code)
    
    return new_user

# --- VERIFY OPTION 1: Via 6-Digit Code ---
@router.post("/verify-email-code")
def verify_email_with_code(payload: VerifyEmailWithCodeSchema, db: Session = Depends(get_db)):
    db_record = db.query(DBEmailVerificationCode).filter(
        DBEmailVerificationCode.email == payload.email,
        DBEmailVerificationCode.code == payload.code
    ).first()
    
    if not db_record:
        raise HTTPException(status_code=400, detail="Invalid verification code or email details.")
        
    if db_record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(db_record)
        db.commit()
        raise HTTPException(status_code=400, detail="The verification code has expired. Please request a new one.")
        
    db_user = db.query(DBUser).filter(DBUser.email == payload.email).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User profile not found.")
        
    if db_user.is_verified:
        db.delete(db_record)
        db.commit()
        return {"message": "Email is already verified."}
        
    # Mark user verified and consume the code
    db_user.is_verified = True
    db.delete(db_record)
    db.commit()
    return {"message": "Email address successfully verified via code!"}


# --- VERIFY OPTION 2: Via Token Link (Stays intact) ---
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
    return {"message": "Email address successfully verified via link!"}


# --- UNIFIED RESEND (Resends both Link + Code) ---
@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationSchema, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.email == payload.email).first()
    
    # Generic messaging protects against malicious user scouting
    if not db_user:
        return {"message": "If the account exists, a new verification link and code have been sent."}
        
    if db_user.is_verified:
        raise HTTPException(status_code=400, detail="This account is already verified.")
        
    # Clear out any previous verification tokens/codes
    db.query(DBEmailVerificationCode).filter(DBEmailVerificationCode.email == db_user.email).delete()
    
    # Regenerate fresh items
    new_v_token = create_verification_token(email=db_user.email)
    new_v_code = generate_numeric_otp(length=6)
    expiry_time = datetime.now(timezone.utc) + timedelta(hours=2)
    
    db_code = DBEmailVerificationCode(email=db_user.email, code=new_v_code, expires_at=expiry_time)
    db.add(db_code)
    db.commit()
    
    background_tasks.add_task(send_combined_verification_email, db_user.email, new_v_token, new_v_code)
    
    return {"message": "If the account exists, a new verification link and code have been sent."}

@router.get("/users/me", response_model=UserResponse)
def read_users_me(current_user: DBUser = Depends(get_current_user)):
    return current_user

