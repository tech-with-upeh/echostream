from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

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


def _sync_database_url(url: str) -> str:
    """Normalize the configured PostgreSQL URL for legacy sync routes."""
    if url.startswith("postgresql+psycopg2://"):
        return url
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg2://" + url.split("://", 1)[1]
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url.split("://", 1)[1]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url.split("://", 1)[1]
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

# Temporary compatibility session for synchronous HTTP handlers. FastAPI runs
# sync route functions in its worker threadpool, so these calls do not block the
# asyncio event loop. Async/WebSocket handlers must use AsyncSessionLocal.
sync_engine = create_engine(
    _sync_database_url(settings.DATABASE_URL),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()
