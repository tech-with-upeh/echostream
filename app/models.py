from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
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

    plan = Column(String, nullable=False, default="starter")
    subscription_status = Column(String, nullable=False, default="active")
    trial_ends_at = Column(DateTime, nullable=True)
    subscription_ends_at = Column(DateTime, nullable=True) 

    refresh_tokens = relationship("DBRefreshToken", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("DBSubscription", back_populates="user", uselist=False, cascade="all, delete-orphan")


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


class DBSubscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    plan = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    paystack_customer_code = Column(String, nullable=True, index=True)
    paystack_subscription_code = Column(String, nullable=True, unique=True, index=True)
    paystack_email_token = Column(String, nullable=True)
    authorization_code = Column(String, nullable=True)
    reference = Column(String, nullable=True, unique=True, index=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    last_event = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    user = relationship("DBUser", back_populates="subscription")
