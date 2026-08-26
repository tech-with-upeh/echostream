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
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequestSchema(BaseModel):
    refresh_token: str

class ResendEmailSchema(BaseModel):
    email: EmailStr

class VerifyEmailWithCodeSchema(BaseModel):
    email: EmailStr
    code: str

class ResendVerificationSchema(BaseModel):
    email: EmailStr

class SocialAuthSchema(BaseModel):
    id_token: str

class TTSTextPayloadSchema(BaseModel):
    text: str = Field(..., description="The text content you want to convert to speech")
    voice: str | None = Field(None, description="Edge voice name or Fish voice model ID")
    provider: str | None = Field(None, description="edge or fish; defaults to the user's preference")
    fish_model: str | None = Field(None, description="Fish model: s2-pro or s2.1-pro-free")
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

class PreferencesSchema(BaseModel):
    tiktok_username: str | None = None
    comment_prefix: str = ""
    comment_suffix: str = ""
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
    speech_prefix_enabled: bool = False
    speech_prefix_template: str = "{{user}} said {{comment}}"
    allowed_user_types: list[str] = Field(default_factory=lambda: ["all"])
    minimum_account_age_days: int = Field(1, ge=0, le=3650)
    blocked_words: list[str] = Field(default_factory=list)
    spam_protection_enabled: bool = False
    block_repeated_words: bool = True
    auto_mute_repeat_offenders: bool = False
    spam_cooldown_seconds: int = Field(2, ge=1, le=60)
    spam_max_requests_per_minute: int = Field(10, ge=1, le=120)
    class Config:
        from_attributes = True

class FishVoiceCloneResponse(BaseModel):
    voice_id: str
    provider: str = "fish"
    message: str
