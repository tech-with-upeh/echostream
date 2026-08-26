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
    return {"Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}", "Content-Type": "application/json", "model": model}


async def stream_tts(text: str, reference_id: str | None = None, model: str | None = None, speed: float = 1.0) -> AsyncIterator[bytes]:
    selected_model = model or settings.FISH_AUDIO_PRO_MODEL
    body: dict[str, object] = {"text": text, "format": settings.FISH_AUDIO_DEFAULT_FORMAT}
    if reference_id:
        body["reference_id"] = reference_id
    if speed != 1.0:
        body["prosody"] = {"speed": speed, "volume": 0, "normalize_loudness": True}

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        try:
            async with client.stream("POST", f"{settings.FISH_AUDIO_BASE_URL}/v1/tts", headers=_headers(selected_model), json=body) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")
                    if response.status_code == 402:
                        detail += " If using s2.1-pro-free, verify that the API key is current and that the free model is available to your account."
                    raise FishAudioError(f"Fish Audio TTS failed ({response.status_code}): {detail}")
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio request failed: {exc}") from exc


async def list_public_voice_models(page_size: int = 50) -> list[dict]:
    """Return only public/unlisted Fish library voices; never private/self-owned clones."""
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")
    headers = {"Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        try:
            response = await client.get(
                f"{settings.FISH_AUDIO_BASE_URL}/model",
                headers=headers,
                params={"page_size": page_size, "page_number": 1, "self": "false", "sort_by": "score"},
            )
            if response.status_code >= 400:
                raise FishAudioError(f"Fish Audio public voice list failed ({response.status_code}): {response.text}")
            payload = response.json()
            return [
                model for model in payload.get("items", [])
                if model.get("_id")
                and model.get("type", "tts") in {"tts", "svc"}
                and model.get("visibility") in {"public", "unlist", None}
            ]
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio public voice list request failed: {exc}") from exc


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
                raise FishAudioError(f"Fish Audio cloned voice list failed ({response.status_code}): {response.text}")
            payload = response.json()
            return [
                model for model in payload.get("items", [])
                if model.get("_id") and model.get("type", "tts") in {"tts", "svc"} and model.get("visibility") == "private"
            ]
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio cloned voice list request failed: {exc}") from exc


async def create_voice_clone(title: str, description: str, tags: list[str], reference_text: str | None, audio_files: list[tuple[str, BinaryIO, str]], enhance_audio_quality: bool = True, generate_sample: bool = False) -> dict:
    """Create a private Fish Audio voice model from one or more reference recordings."""
    if not settings.FISH_AUDIO_API_KEY:
        raise FishAudioError("Fish Audio is not configured. Set FISH_AUDIO_API_KEY.")
    if not audio_files:
        raise FishAudioError("At least one audio reference is required.")

    data = {
        "type": "tts",
        "title": title,
        "description": description,
        "visibility": "private",
        "train_mode": "fast",
        "enhance_audio_quality": str(enhance_audio_quality).lower(),
        "generate_sample": str(generate_sample).lower(),
    }
    if tags:
        data["tags"] = ",".join(tag.strip() for tag in tags if tag.strip())
    if reference_text:
        data["text"] = reference_text

    files = [("voices", item) for item in audio_files]
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        try:
            response = await client.post(
                f"{settings.FISH_AUDIO_BASE_URL}/model",
                headers={"Authorization": f"Bearer {settings.FISH_AUDIO_API_KEY}"},
                data=data,
                files=files,
            )
            if response.status_code >= 400:
                raise FishAudioError(f"Fish Audio voice cloning failed ({response.status_code}): {response.text}")
            payload = response.json()
            voice_id = payload.get("_id")
            if not voice_id:
                raise FishAudioError("Fish Audio did not return a voice model ID.")
            return payload
        except httpx.HTTPError as exc:
            raise FishAudioError(f"Fish Audio voice request failed: {exc}") from exc
