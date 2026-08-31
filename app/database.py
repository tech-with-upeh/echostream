from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings


def _async_database_url(url: str) -> str:
    """Normalize the configured PostgreSQL URL for SQLAlchemy's async driver."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


engine = create_async_engine(
    _async_database_url(settings.DATABASE_URL),
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
Base = declarative_base()
