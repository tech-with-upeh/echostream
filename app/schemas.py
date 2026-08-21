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
    voice: str = Field("en-US-GuyNeural", description="The Microsoft Edge TTS voice model name")

class VoiceDetailSchema(BaseModel):
    name: str
    short_name: str
    gender: str
    locale: str
