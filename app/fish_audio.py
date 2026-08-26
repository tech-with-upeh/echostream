from collections.abc import AsyncIterator
from typing import BinaryIO

import httpx

from app.config import settings


class FishAudioError(RuntimeError):
    """Raised when Fish Audio cannot synthesize or create a voice."""


def _headers(model: str | None = None) -> dict[str, str]:
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")

    headers = {
        "Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}",
        "Content-Type": "application/json",
    }
    if model:
        headers["model"] = model
    return headers


async def stream_tts(
    text: str,
    reference_id: str | None = None,
    model: str | None = None,
    speed: float = 1.0,
) -> AsyncIterator[bytes]:
    """Stream Fish Audio TTS bytes without exposing the provider key to clients."""
    body = {
        "text": text,
        "format": settings.FISH_AUDIO_DEFAULT_FORMAT,
        "sample_rate": settings.FISH_AUDIO_DEFAULT_SAMPLE_RATE,
        "mp3_bitrate": settings.FISH_AUDIO_DEFAULT_BITRATE,
        "prosody": {"speed": speed, "volume": 0, "normalize_loudness": True},
    }
    if reference_id:
        body["reference_id"] = reference_id

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        try:
            async with client.stream(
                "POST",
                f"{settings.FISH_AUDIO_BASE_URL}/v1/tts",
                headers=_headers(model or settings.FISH_AUDIO_PRO_MODEL),
                json=body,
            ) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")
                    raise FishAudioError(f"Fish Audio TTS failed ({response.status_code}): {detail}")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio request failed: {exc}") from exc


async def create_voice_clone(
    title: str,
    audio: BinaryIO,
    filename: str,
    content_type: str | None,
) -> str:
    """Create a private reusable Fish Audio voice model and return its ID."""
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")

    files = {
        "voices": (filename, audio, content_type or "application/octet-stream"),
    }
    data = {
        "type": "tts",
        "title": title,
        "train_mode": "fast",
        "visibility": "private",
        "description": "EchoStream Pro voice clone",
        "enhance_audio_quality": "true",
        "generate_sample": "false",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        try:
            response = await client.post(
                f"{settings.FISH_AUDIO_BASE_URL}/model",
                headers={"Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}"},
                data=data,
                files=files,
            )
            if response.status_code >= 400:
                detail = response.text
                raise FishAudioError(
                    f"Fish Audio voice cloning failed ({response.status_code}): {detail}"
                )
            payload = response.json()
            voice_id = payload.get("_id")
            if not voice_id:
                raise FishAudioError("Fish Audio did not return a voice model ID.")
            return voice_id
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio voice request failed: {exc}") from exc
