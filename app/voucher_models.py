from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base

UTCDateTime = DateTime(timezone=True)


class DBRedeemCode(Base):
    __tablename__ = "redeem_codes"
    __table_args__ = (UniqueConstraint("code_hash"),)

    id = Column(Integer, primary_key=True, index=True)
    code_hash = Column(String, nullable=False, index=True)
    code_prefix = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)  # subscription | voucher
    plan = Column(String, nullable=True, index=True)
    duration_days = Column(Integer, nullable=True)
    credit_kobo = Column(Integer, nullable=False, default=0)
    max_redemptions = Column(Integer, nullable=True)
    redemption_count = Column(Integer, nullable=False, default=0)
    starts_at = Column(UTCDateTime, nullable=True)
    expires_at = Column(UTCDateTime, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(UTCDateTime, nullable=False)
    updated_at = Column(UTCDateTime, nullable=False)


class DBRedeemCodeRedemption(Base):
    __tablename__ = "redeem_code_redemptions"
    __table_args__ = (UniqueConstraint("redeem_code_id", "user_id"),)

    id = Column(Integer, primary_key=True, index=True)
    redeem_code_id = Column(Integer, ForeignKey("redeem_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, default="consumed", index=True)
    plan = Column(String, nullable=True)
    duration_days = Column(Integer, nullable=True)
    credit_kobo = Column(Integer, nullable=False, default=0)
    checkout_reference = Column(String, nullable=True, unique=True, index=True)
    redeemed_at = Column(UTCDateTime, nullable=True)
    created_at = Column(UTCDateTime, nullable=False)
    updated_at = Column(UTCDateTime, nullable=False)


class DBUserCredit(Base):
    __tablename__ = "user_credits"
    __table_args__ = (UniqueConstraint("user_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    balance_kobo = Column(Integer, nullable=False, default=0)
    created_at = Column(UTCDateTime, nullable=False)
    updated_at = Column(UTCDateTime, nullable=False)


class DBUserCreditLedger(Base):
    __tablename__ = "user_credit_ledger"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_kobo = Column(Integer, nullable=False)
    balance_after_kobo = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    reference = Column(String, nullable=False, unique=True, index=True)
    redeem_code_id = Column(Integer, ForeignKey("redeem_codes.id", ondelete="SET NULL"), nullable=True, index=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(UTCDateTime, nullable=False)
