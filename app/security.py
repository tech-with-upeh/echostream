from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from app.config import settings
import secrets

# Keep password and token helpers intact...
def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)

def create_access_token(user_id: int, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": str(user_id), "type": "access", "exp": expire, "token_version": token_version}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)

def create_refresh_token(user_id: int, token_version: int = 0) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {"sub": str(user_id), "type": "refresh", "exp": expires_at, "token_version": token_version}
    token_string = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)
    return token_string, expires_at

# Added: Generates a verification token valid for 2 hours
def create_verification_token(email: str, ttl_in_hours: int = 2) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ttl_in_hours)
    to_encode = {"sub": email, "type": "verification", "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)

def generate_numeric_otp(length: int = 6) -> str:
    """Generates a cryptographically secure numeric string of specified length."""
    return "".join(secrets.choice("0123456789") for _ in range(length))
