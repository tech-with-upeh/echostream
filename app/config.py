import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 1. Force find your root folder dynamically from this file's position
# app/config.py is inside 'app/', so .parent.parent gets the project root
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# 2. Explicitly load the text variables into system memory using python-dotenv
load_dotenv(dotenv_path=ENV_PATH)

# 3. Let Pydantic comfortably extract and validate from system memory
class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # SMTP Configurations
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_PORT: int
    MAIL_SERVER: str
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    
    FRONTEND_URL: str

    GOOGLE_CLIENT_ID: str
    # Cleaned up: No more messy relative string paths needed here!
settings = Settings()

