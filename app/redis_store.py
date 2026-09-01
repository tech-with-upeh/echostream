import json
from typing import Any

import redis.asyncio as redis

from app.config import settings


_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def ping_redis() -> None:
    await get_redis().ping()


async def publish(channel: str, payload: dict[str, Any]) -> int:
    return await get_redis().publish(channel, json.dumps(payload, separators=(",", ":")))


async def get_json(key: str) -> dict[str, Any] | None:
    value = await get_redis().get(key)
    if value is None:
        return None
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


async def set_json(key: str, value: dict[str, Any], *, ex: int | None = None) -> None:
    await get_redis().set(key, json.dumps(value, separators=(",", ":")), ex=ex)


async def delete(key: str) -> None:
    await get_redis().delete(key)
