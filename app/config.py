from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_PORT: int
    MAIL_SERVER: str
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    FRONTEND_URL: str
    GOOGLE_CLIENT_ID: str

    PAYSTACK_SECRET_KEY: str
    PAYSTACK_PUBLIC_KEY: str = ""
    PAYSTACK_ESSENTIAL_PLAN_CODE: str = ""
    PAYSTACK_PRO_PLAN_CODE: str = ""
    PAYSTACK_ESSENTIAL_MONTHLY_PLAN_CODE: str = ""
    PAYSTACK_ESSENTIAL_YEARLY_PLAN_CODE: str = ""
    PAYSTACK_PRO_MONTHLY_PLAN_CODE: str = ""
    PAYSTACK_PRO_YEARLY_PLAN_CODE: str = ""
    PAYSTACK_ESSENTIAL_MONTHLY_USD: float = 5.0
    PAYSTACK_ESSENTIAL_YEARLY_USD: float = 50.0
    PAYSTACK_PRO_MONTHLY_USD: float = 10.0
    PAYSTACK_PRO_YEARLY_USD: float = 100.0
    PAYSTACK_PRICE_CHANGE_THRESHOLD_PERCENT: float = 5.0
    PAYSTACK_PLAN_SYNC_SECRET: str = ""
    PAYSTACK_CALLBACK_URL: str

    # Cloudflare R2 storage. Keep all credentials server-side.
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    R2_PUBLIC_BASE_URL: str

    # Fish Audio is a server-side integration. Never expose this key to the client.
    FISH_AUDIO_API_KEY: str = ""
    FISH_AUDIO_BASE_URL: str = "https://api.fish.audio"
    FISH_AUDIO_PRO_MODEL: str = "s2-pro"
    FISH_AUDIO_FREE_MODEL: str = "s2.1-pro-free"
    FISH_AUDIO_DEFAULT_FORMAT: str = "mp3"
    FISH_AUDIO_DEFAULT_SAMPLE_RATE: int = 44100
    FISH_AUDIO_DEFAULT_BITRATE: int = 128


settings = Settings()
