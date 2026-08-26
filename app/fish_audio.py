from collections.abc import AsyncIterator
from typing import BinaryIO

import httpx

from app.config import settings


class FishAudioError(RuntimeError):
    """Raised when Fish Audio cannot synthesize or create a voice."""


def _headers(model: str) -> dict[str, str]:
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")

    if model not in {settings.FISH_AUDIO_PRO_MODEL, settings.FISH_AUDIO_FREE_MODEL}:
        raise FishAudioError(f"Unsupported Fish Audio model: {model}")

    return {
        "Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}",
        "Content-Type": "application/json",
        "model": model,
    }


async def stream_tts(
    text: str,
    reference_id: str | None = None,
    model: str | None = None,
    speed: float = 1.0,
) -> AsyncIterator[bytes]:
    """Stream Fish Audio TTS bytes without exposing the provider key to clients."""
    selected_model = model or settings.FISH_AUDIO_PRO_MODEL

    body: dict[str, object] = {"text": text, "format": settings.FISH_AUDIO_DEFAULT_FORMAT}
    if reference_id:
        body["reference_id"] = reference_id
    if speed != 1.0:
        body["prosody"] = {
            "speed": speed,
            "volume": 0,
            "normalize_loudness": True,
        }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        try:
            async with client.stream(
                "POST",
                f"{settings.FISH_AUDIO_BASE_URL}/v1/tts",
                headers=_headers(selected_model),
                json=body,
            ) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")
                    if response.status_code == 402:
                        detail = (
                            f"{detail} If using s2.1-pro-free, verify that the API key is "
                            "a current Fish Audio API key and that the free model is "
                            "available to your account."
                        )
                    raise FishAudioError(f"Fish Audio TTS failed ({response.status_code}): {detail}")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio request failed: {exc}") from exc


async def list_voice_models(page_size: int = 50) -> list[dict]:
    """Return public Fish voice models plus models owned by the API workspace."""
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")

    headers = {"Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}"}
    models: list[dict] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        try:
            for params in (
                {"page_size": page_size, "page_number": 1, "self": "false", "sort_by": "score"},
                {"page_size": page_size, "page_number": 1, "self": "true", "sort_by": "created_at"},
            ):
                response = await client.get(
                    f"{settings.FISH_AUDIO_BASE_URL}/model", headers=headers, params=params
                )
                if response.status_code >= 400:
                    raise FishAudioError(
                        f"Fish Audio voice list failed ({response.status_code}): {response.text}"
                    )

                payload = response.json()
                for model in payload.get("items", []):
                    model_id = model.get("_id")
                    if model_id and model.get("type", "tts") in {"tts", "svc"}:
                        models.append(model)
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio voice list request failed: {exc}") from exc

    unique: dict[str, dict] = {}
    for model in models:
        unique[model["_id"]] = model
    return list(unique.values())


async def list_owned_voice_models(page_size: int = 50) -> list[dict]:
    """Return only Fish voice models owned by the EchoStream Fish workspace."""
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")

    headers = {"Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        try:
            response = await client.get(
                f"{settings.FISH_AUDIO_BASE_URL}/model",
                headers=headers,
                params={"page_size": page_size, "page_number": 1, "self": "true", "sort_by": "created_at"},
            )
            if response.status_code >= 400:
                raise FishAudioError(
                    f"Fish Audio cloned voice list failed ({response.status_code}): {response.text}"
                )
            payload = response.json()
            return [
                model
                for model in payload.get("items", [])
                if model.get("_id") and model.get("type", "tts") in {"tts", "svc"}
            ]
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio cloned voice list request failed: {exc}") from exc


async def create_voice_clone(
    title: str,
    audio: BinaryIO,
    filename: str,
    content_type: str | None,
) -> str:
    """Create a private reusable Fish Audio voice model and return its ID."""
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")

    files = {"voices": (filename, audio, content_type or "application/octet-stream")}
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
                raise FishAudioError(
                    f"Fish Audio voice cloning failed ({response.status_code}): {response.text}"
                )
            payload = response.json()
            voice_id = payload.get("_id")
            if not voice_id:
                raise FishAudioError("Fish Audio did not return a voice model ID.")
            return voice_id
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio voice request failed: {exc}") from exc
