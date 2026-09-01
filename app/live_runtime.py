import asyncio
import os
import socket
import uuid
from typing import Any

from app.config import settings
from app.redis_store import delete, get_json, get_redis, publish, set_json

_STATE_PREFIX = "echostream:live:state:"
_OWNER_PREFIX = "echostream:live:owner:"
_EVENT_PREFIX = "echostream:live:events:"
_COMMAND_PREFIX = "echostream:live:commands:"
_TTS_OWNER_PREFIX = "echostream:live:tts-owner:"
_OWNER_TTL = 60

INSTANCE_ID = settings.INSTANCE_ID or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

_ACQUIRE = """
local current = redis.call('GET', KEYS[1])
if current then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2], 'NX')
return 1
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
_REFRESH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


def state_key(user_id: int) -> str:
    return f"{_STATE_PREFIX}{user_id}"


def owner_key(user_id: int) -> str:
    return f"{_OWNER_PREFIX}{user_id}"


def event_channel(user_id: int) -> str:
    return f"{_EVENT_PREFIX}{user_id}"


def command_channel(instance_id: str = INSTANCE_ID) -> str:
    return f"{_COMMAND_PREFIX}{instance_id}"


def tts_owner_key(user_id: int) -> str:
    return f"{_TTS_OWNER_PREFIX}{user_id}"


async def get_live_status(user_id: int, username: str | None = None) -> dict[str, Any]:
    state = await get_json(state_key(user_id))
    if state is None:
        return {"status": "stopped", "username": username, "error": None}
    if username and not state.get("username"):
        state["username"] = username
    return state


async def set_live_state(user_id: int, status: str, *, username: str | None = None, error: str | None = None) -> dict[str, Any]:
    current = await get_live_status(user_id, username=username)
    state = {
        "status": status,
        "username": username or current.get("username"),
        "error": error,
        "owner": await get_redis().get(owner_key(user_id)),
    }
    await set_json(state_key(user_id), state, ex=_OWNER_TTL)
    await publish(event_channel(user_id), {"type": "live_state", **state})
    return state


async def acquire_live_owner(user_id: int) -> bool:
    result = await get_redis().eval(_ACQUIRE, 1, owner_key(user_id), INSTANCE_ID, _OWNER_TTL)
    if result:
        await set_json(state_key(user_id), {"status": "connecting", "owner": INSTANCE_ID}, ex=_OWNER_TTL)
    return bool(result)


async def refresh_live_owner(user_id: int) -> bool:
    result = await get_redis().eval(_REFRESH, 1, owner_key(user_id), INSTANCE_ID, _OWNER_TTL)
    if result:
        await get_redis().expire(state_key(user_id), _OWNER_TTL)
    return bool(result)


async def release_live_owner(user_id: int) -> None:
    await get_redis().eval(_RELEASE, 1, owner_key(user_id), INSTANCE_ID)
    await delete(state_key(user_id))


async def publish_live_event(user_id: int, item: dict[str, Any]) -> int:
    return await publish(event_channel(user_id), {"type": "tts_event", "item": item})


async def request_stop(user_id: int) -> str | None:
    owner = await get_redis().get(owner_key(user_id))
    if owner and owner != INSTANCE_ID:
        await publish(command_channel(owner), {"command": "stop", "user_id": user_id})
        return owner
    if owner == INSTANCE_ID:
        await publish(command_channel(INSTANCE_ID), {"command": "stop", "user_id": user_id})
        return owner
    return None


async def acquire_tts_owner(user_id: int, ttl: int = 120) -> bool:
    result = await get_redis().eval(_ACQUIRE, 1, tts_owner_key(user_id), INSTANCE_ID, ttl)
    return bool(result)


async def refresh_tts_owner(user_id: int, ttl: int = 120) -> bool:
    result = await get_redis().eval(_REFRESH, 1, tts_owner_key(user_id), INSTANCE_ID, ttl)
    return bool(result)


async def release_tts_owner(user_id: int) -> None:
    await get_redis().eval(_RELEASE, 1, tts_owner_key(user_id), INSTANCE_ID)


async def command_listener(stop_event: asyncio.Event) -> None:
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(command_channel(INSTANCE_ID))
    try:
        async for message in pubsub.listen():
            if stop_event.is_set():
                break
            if message.get("type") != "message":
                continue
            import json
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            if payload.get("command") == "stop":
                from app.tiktok_manager import stop_tiktok_session
                await stop_tiktok_session(int(payload["user_id"]))
    finally:
        await pubsub.close()


async def owner_heartbeat(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            from app.tiktok_manager import active_tiktok_clients
            for user_id in list(active_tiktok_clients):
                await refresh_live_owner(user_id)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass


async def mark_live_ready(user_id: int, *, username: str | None = None) -> None:
    await set_live_state(user_id, "ready", username=username)


async def mark_live_failed(user_id: int, reason: str) -> None:
    state = await set_live_state(user_id, "failed", error=reason)
    await publish(event_channel(user_id), {"type": "live_error", "error": reason, "state": state})
    await release_live_owner(user_id)


async def stop_runtime_session(user_id: int) -> None:
    await set_live_state(user_id, "stopped")
    await release_live_owner(user_id)
