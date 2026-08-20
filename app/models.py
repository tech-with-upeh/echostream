from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.database import Base

class DBUser(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    # --- Plan tier vs. subscription state, kept separate on purpose ---
    plan = Column(String, default="free", nullable=False)          # free, basic, essential, pro
    subscription_status = Column(String, default="active")         # active, trialing, past_due, canceled, expired
    trial_ends_at = Column(DateTime, nullable=True)                # only set while trialing a PAID plan
    subscription_ends_at = Column(DateTime, nullable=True)

    refresh_tokens = relationship("DBRefreshToken", back_populates="user", cascade="all, delete-orphan")

class DBRefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    user = relationship("DBUser", back_populates="refresh_tokens")

class DBEmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    code = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class DBUserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    tiktok_username = Column(String, nullable=True)   # e.g. "upeh_gaming"

    comment_prefix = Column(String, default="")
    comment_suffix = Column(String, default="")
    voice = Column(String, default="en-US-GuyNeural")
    pitch = Column(String, default="+0Hz")
