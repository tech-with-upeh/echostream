from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from app.database import Base


class DBSubscriptionUpgrade(Base):
    __tablename__ = "subscription_upgrades"
    __table_args__ = (UniqueConstraint("reference"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)

    reference = Column(String, nullable=False, unique=True, index=True)
    payment_reference = Column(String, nullable=True, unique=True, index=True)

    old_plan = Column(String, nullable=False)
    old_interval = Column(String, nullable=False)
    old_subscription_code = Column(String, nullable=False)
    old_authorization_code = Column(String, nullable=True)
    old_period_start = Column(DateTime(timezone=True), nullable=True)
    old_period_end = Column(DateTime(timezone=True), nullable=True)

    new_plan = Column(String, nullable=False)
    new_interval = Column(String, nullable=False)
    new_subscription_code = Column(String, nullable=True, index=True)
    new_authorization_code = Column(String, nullable=True)

    total_seconds = Column(Integer, nullable=False, default=0)
    remaining_seconds = Column(Integer, nullable=False, default=0)
    old_plan_price_kobo = Column(Integer, nullable=False)
    new_plan_price_kobo = Column(Integer, nullable=False)
    unused_value_kobo = Column(Integer, nullable=False, default=0)
    upgrade_amount_kobo = Column(Integer, nullable=False, default=0)
    credit_duration_seconds = Column(Integer, nullable=False, default=0)

    first_debit = Column(DateTime(timezone=True), nullable=False)
    payment_amount_kobo = Column(Integer, nullable=True)
    payment_channel = Column(String, nullable=True)

    status = Column(String, nullable=False, default="pending_payment", index=True)
    last_error = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
