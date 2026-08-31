from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

UTCDateTime = DateTime(timezone=True)

class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    plan = Column(String, nullable=False, default="starter")
    subscription_status = Column(String, nullable=False, default="active")
    trial_ends_at = Column(UTCDateTime, nullable=True)
    subscription_ends_at = Column(UTCDateTime, nullable=True)
    refresh_tokens = relationship("DBRefreshToken", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("DBSubscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    preferences = relationship("DBUserPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")
    fish_voices = relationship("DBFishVoice", back_populates="user", cascade="all, delete-orphan")
    muted_users = relationship("DBMutedUser", back_populates="owner", cascade="all, delete-orphan")
    gift_preferences = relationship("DBGiftPreference", back_populates="owner", cascade="all, delete-orphan")
    audio_assets = relationship("DBAudioAsset", back_populates="owner", cascade="all, delete-orphan")

class DBAudioAsset(Base):
    __tablename__ = "audio_assets"
    __table_args__ = (UniqueConstraint("r2_key"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    r2_key = Column(String, nullable=False, index=True)
    public_url = Column(String, unique=True, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(UTCDateTime, nullable=False)
    updated_at = Column(UTCDateTime, nullable=False)
    owner = relationship("DBUser", back_populates="audio_assets")

class DBRefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(UTCDateTime, nullable=False)
    user = relationship("DBUser", back_populates="refresh_tokens")

class DBEmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    code = Column(String, nullable=False)
    expires_at = Column(UTCDateTime, nullable=False)

class DBResetPassVerificationCode(Base):
    __tablename__ = "pass_reset_verification_codes"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    code = Column(String, nullable=False)
    token = Column(String, nullable=True)
    expires_at = Column(UTCDateTime, nullable=False)

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
    current_period_start = Column(UTCDateTime, nullable=True)
    current_period_end = Column(UTCDateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False)
    last_event = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(UTCDateTime, nullable=False)
    updated_at = Column(UTCDateTime, nullable=False)
    user = relationship("DBUser", back_populates="subscription")

class DBUserPreferences(Base):
    __tablename__ = "user_preferences"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    tiktok_username = Column(String, nullable=True)
    tts_provider = Column(String, nullable=False, default="edge")
    voice = Column(String, nullable=False, default="en-US-GuyNeural")
    fish_voice_id = Column(String, nullable=True)
    fish_model = Column(String, nullable=False, default="s2-pro")
    pitch = Column(String, nullable=False, default="+0Hz")
    volume = Column(Integer, nullable=False, default=100)
    speed = Column(Integer, nullable=False, default=100)
    emoji_to_words = Column(Boolean, nullable=False, default=False)
    filter_profanity = Column(Boolean, nullable=False, default=False)
    require_command_prefix = Column(Boolean, nullable=False, default=False)
    max_message_length = Column(Integer, nullable=False, default=100)
    comment_speech_enabled = Column(Boolean, nullable=False, default=False)
    comment_speech_template = Column(String, nullable=False, default="{{user}} said {{comment}}")
    event_speech_enabled = Column(Boolean, nullable=False, default=False)
    event_speech_template = Column(String, nullable=False, default="{{user}} sent {{event}}")
    gift_alert_enabled = Column(Boolean, nullable=False, default=False)
    gift_alert_type = Column(String, nullable=False, default="tts")
    gift_tts_template = Column(String, nullable=False, default="{{user}} sent {{gift}}")
    gift_tts_voice = Column(String, nullable=True)
    gift_tts_provider = Column(String, nullable=True)
    gift_fish_voice_id = Column(String, nullable=True)
    gift_fish_model = Column(String, nullable=True)
    gift_system_sound_id = Column(String, nullable=True)
    gift_custom_audio_id = Column(Integer, ForeignKey("audio_assets.id", ondelete="SET NULL"), nullable=True)
    gift_custom_audio_url = Column(String, nullable=True)
    gift_volume = Column(Integer, nullable=False, default=100)
    gift_speed = Column(Integer, nullable=False, default=100)
    allowed_user_types = Column(String, nullable=False, default='["all"]')
    minimum_account_age_days = Column(Integer, nullable=False, default=1)
    blocked_words = Column(Text, nullable=False, default="[]")
    spam_protection_enabled = Column(Boolean, nullable=False, default=False)
    block_repeated_words = Column(Boolean, nullable=False, default=True)
    auto_mute_repeat_offenders = Column(Boolean, nullable=False, default=False)
    spam_cooldown_seconds = Column(Integer, nullable=False, default=2)
    spam_max_requests_per_minute = Column(Integer, nullable=False, default=10)
    user = relationship("DBUser", back_populates="preferences")
    gift_custom_audio = relationship("DBAudioAsset", foreign_keys=[gift_custom_audio_id])

class DBGiftPreference(Base):
    __tablename__ = "gift_preferences"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    gift_id = Column(String, nullable=False)
    gift_name = Column(String, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    alert_type = Column(String, nullable=False, default="tts")
    tts_template = Column(String, nullable=True)
    tts_provider = Column(String, nullable=True)
    voice = Column(String, nullable=True)
    fish_voice_id = Column(String, nullable=True)
    fish_model = Column(String, nullable=True)
    system_sound_id = Column(String, nullable=True)
    custom_audio_id = Column(Integer, ForeignKey("audio_assets.id", ondelete="SET NULL"), nullable=True)
    custom_audio_url = Column(String, nullable=True)
    volume = Column(Integer, nullable=True)
    speed = Column(Integer, nullable=True)
    pitch = Column(String, nullable=True)
    owner = relationship("DBUser", back_populates="gift_preferences")
    custom_audio = relationship("DBAudioAsset", foreign_keys=[custom_audio_id])

class DBFishVoice(Base):
    __tablename__ = "fish_voices"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    voice_id = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    model = Column(String, nullable=False, default="s2-pro")
    created_at = Column(UTCDateTime, nullable=False)
    user = relationship("DBUser", back_populates="fish_voices")

class DBMutedUser(Base):
    __tablename__ = "muted_users"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tiktok_user_id = Column(String, nullable=True, index=True)
    tiktok_username = Column(String, nullable=False)
    reason = Column(String, nullable=False, default="manual")
    created_at = Column(UTCDateTime, nullable=False)
    owner = relationship("DBUser", back_populates="muted_users")
