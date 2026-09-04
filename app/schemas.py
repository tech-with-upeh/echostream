from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional

class UserRegisterSchema(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
class UserLoginSchema(BaseModel):
    email: EmailStr
    password: str
class UserForgotPasswordSchema(BaseModel): email: EmailStr
class UserResetPasswordSchema(BaseModel):
    token: str
    email: EmailStr
    password: str
class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    is_verified: bool
    plan: str
    subscription_status: str
    trial_ends_at: Optional[datetime] = None
    subscription_ends_at: Optional[datetime] = None
    class Config: from_attributes = True
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
class RefreshRequestSchema(BaseModel): refresh_token: str
class ResendEmailSchema(BaseModel): email: EmailStr
class VerifyEmailWithCodeSchema(BaseModel):
    email: EmailStr
    code: str
class ResendVerificationSchema(BaseModel): email: EmailStr
class SocialAuthSchema(BaseModel): id_token: str
class TTSTextPayloadSchema(BaseModel):
    text: str
    voice: str | None = None
    provider: str | None = None
    fish_model: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
class VoiceDetailSchema(BaseModel):
    name: str
    short_name: str
    gender: str
    locale: str
class FishVoiceDetailSchema(BaseModel):
    id: str
    name: str
    provider: str = "fish"
    voice_type: str = "library"
    description: str = ""
    languages: list[str] = Field(default_factory=list)
    visibility: str = "public"
class TTSVoiceCatalogSchema(BaseModel):
    edge: list[VoiceDetailSchema]
    fish: list[FishVoiceDetailSchema] = Field(default_factory=list)
class AudioAssetResponse(BaseModel):
    id: int
    name: str
    public_url: str
    created_at: datetime
    updated_at: datetime
    class Config: from_attributes = True
class GiftAlertPreferenceSchema(BaseModel):
    enabled: bool = True
    alert_type: str = Field("tts", pattern="^(tts|system_sound|custom_audio)$")
    tts_template: str | None = "{{user}} sent {{gift}}"
    tts_provider: str | None = Field(None, pattern="^(edge|fish)$")
    voice: str | None = None
    fish_voice_id: str | None = None
    fish_model: str | None = Field(None, pattern="^(s2-pro|s2\.1-pro-free)$")
    system_sound_id: str | None = None
    custom_audio_id: int | None = None
    custom_audio_url: str | None = None
    volume: int | None = Field(None, ge=0, le=100)
    speed: int | None = Field(None, ge=50, le=200)
    pitch: str | None = None
class GiftPreferenceResponse(GiftAlertPreferenceSchema):
    id: int
    gift_id: str
    gift_name: str
class GenericGiftPreferenceSchema(GiftAlertPreferenceSchema): pass
class EventAlertPreferenceSchema(GiftAlertPreferenceSchema):
    tts_template: str | None = "{{user}} {{event}}"
class EventAlertPreferenceResponse(EventAlertPreferenceSchema):
    event_type: str
class TikTokGiftSchema(BaseModel):
    id: str
    name: str
    diamond_count: int | None = None
    type: int | None = None
    image_url: str | None = None
class PreferencesSchema(BaseModel):
    tiktok_username: str | None = None
    tts_provider: str = Field("edge", pattern="^(edge|fish)$")
    voice: str = "en-US-GuyNeural"
    fish_voice_id: str | None = None
    fish_model: str = Field("s2-pro", pattern="^(s2-pro|s2\.1-pro-free)$")
    pitch: str = "+0Hz"
    volume: int = Field(100, ge=0, le=100)
    speed: int = Field(100, ge=50, le=200)
    emoji_to_words: bool = False
    filter_profanity: bool = False
    require_command_prefix: bool = False
    max_message_length: int = Field(100, ge=1, le=500)
    comment_speech_enabled: bool = False
    comment_speech_template: str = "{{user}} said {{comment}}"
    events: dict[str, EventAlertPreferenceSchema] = Field(default_factory=dict)
    allowed_user_types: list[str] = Field(default_factory=lambda: ["all"])
    minimum_account_age_days: int = Field(1, ge=0, le=3650)
    blocked_words: list[str] = Field(default_factory=list)
    spam_protection_enabled: bool = False
    block_repeated_words: bool = True
    auto_mute_repeat_offenders: bool = False
    spam_cooldown_seconds: int = Field(2, ge=1, le=60)
    spam_max_requests_per_minute: int = Field(10, ge=1, le=120)
    class Config: from_attributes = True
class PaymentHistoryItem(BaseModel):
    id: int
    payment_id: str
    receipt_number: str
    provider: str
    provider_reference: str
    billing_type: str
    method: str | None = None
    method_brand: str | None = None
    method_last4: str | None = None
    reference: str
    plan: str
    interval: str | None = None
    amount: int | None = None
    currency: str = "NGN"
    status: str
    event: str
    paid_at: datetime | None = None
    created_at: datetime
    class Config: from_attributes = True
class PaymentHistoryResponse(BaseModel):
    items: list[PaymentHistoryItem]
    total: int
    page: int
    per_page: int
class PaymentReceiptCustomer(BaseModel):
    name: str
    email: EmailStr
class PaymentReceiptPayment(BaseModel):
    payment_id: str
    receipt_number: str
    provider: str
    provider_reference: str
    plan: str
    interval: str | None = None
    billing_type: str
    method: str | None = None
    amount: int | None = None
    currency: str
    status: str
    paid_at: datetime | None = None
class PaymentReceiptSubscription(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
class PaymentReceiptResponse(BaseModel):
    customer: PaymentReceiptCustomer
    payment: PaymentReceiptPayment
    subscription: PaymentReceiptSubscription
    issued_at: datetime
class FishVoiceCloneResponse(BaseModel):
    voice_id: str
    provider: str = "fish"
    message: str