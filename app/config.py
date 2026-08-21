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

    # Existing/legacy plan codes. Kept as a fallback for existing monthly
    # plans while the new monthly/yearly plans are introduced.
    PAYSTACK_ESSENTIAL_PLAN_CODE: str = ""
    PAYSTACK_PRO_PLAN_CODE: str = ""

    # New monthly/yearly plan codes. These are populated after creating the
    # plans in Paystack and can also be created by the plan sync endpoint.
    PAYSTACK_ESSENTIAL_MONTHLY_PLAN_CODE: str = ""
    PAYSTACK_ESSENTIAL_YEARLY_PLAN_CODE: str = ""
    PAYSTACK_PRO_MONTHLY_PLAN_CODE: str = ""
    PAYSTACK_PRO_YEARLY_PLAN_CODE: str = ""

    # USD price anchors. Paystack itself remains NGN; these values are used
    # to calculate the desired NGN price from the current USD/NGN rate.
    PAYSTACK_ESSENTIAL_MONTHLY_USD: float = 5.0
    PAYSTACK_ESSENTIAL_YEARLY_USD: float = 50.0
    PAYSTACK_PRO_MONTHLY_USD: float = 10.0
    PAYSTACK_PRO_YEARLY_USD: float = 100.0

    # Don't constantly change prices for tiny FX movements.
    PAYSTACK_PRICE_CHANGE_THRESHOLD_PERCENT: float = 5.0

    # Protects the administrative plan-sync endpoint.
    PAYSTACK_PLAN_SYNC_SECRET: str = ""

    PAYSTACK_CALLBACK_URL: str


settings = Settings()
