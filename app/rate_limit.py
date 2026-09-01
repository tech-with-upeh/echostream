import logging
import time
from typing import Callable

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.redis_store import get_redis

logger = logging.getLogger(__name__)


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """Shared fixed-window rate limiter backed by Redis."""

    def _identity(self, request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = jwt.decode(auth[7:].strip(), settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM], options={"verify_exp": False})
                if payload.get("sub"):
                    return f"user:{payload['sub']}"
            except Exception:
                pass
        return f"ip:{request.client.host if request.client else 'unknown'}"

    def _limit_for(self, request: Request) -> tuple[str, int]:
        path = request.url.path.rstrip("/") or "/"
        method = request.method.upper()
        if path in {"/docs", "/redoc", "/openapi.json", "/"} or method == "OPTIONS":
            return "skip", 0
        auth_paths = {
            "/login", "/register", "/refresh", "/auth/google", "/logout",
            "/forgot-password", "/reset-password", "/reset-pass-code",
            "/verify-email", "/verify-email-code", "/resend-verification",
        }
        if path in auth_paths:
            return "auth", settings.RATE_LIMIT_AUTH_PER_MINUTE
        if path == "/v1/tts":
            return "tts", settings.RATE_LIMIT_TTS_PER_MINUTE
        if path == "/v1/tts/fish/clone":
            return "clone", settings.RATE_LIMIT_CLONE_PER_MINUTE
        if path == "/v1/live/start":
            return "live-start", settings.RATE_LIMIT_LIVE_START_PER_MINUTE
        if path.startswith("/v1/"):
            return "api", settings.RATE_LIMIT_API_PER_MINUTE
        return "public", settings.RATE_LIMIT_PUBLIC_PER_MINUTE

    async def dispatch(self, request: Request, call_next: Callable):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        category, limit = self._limit_for(request)
        if category == "skip":
            return await call_next(request)
        window = max(1, settings.RATE_LIMIT_WINDOW_SECONDS)
        bucket = int(time.time()) // window
        key = f"echostream:ratelimit:{category}:{self._identity(request)}:{bucket}"

        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window + 1)
        except Exception:
            # Rate limiting is a protective feature, not a hard dependency for the API.
            logger.warning(
                "Redis rate limiter unavailable; allowing request through",
                exc_info=True,
            )
            return await call_next(request)

        if count > limit:
            retry_after = window - (int(time.time()) % window)
            return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again later."}, headers={"Retry-After": str(retry_after)})
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response
