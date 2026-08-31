import asyncio
from urllib.parse import urlparse
from uuid import uuid4

import boto3
import magic
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings


class R2StorageError(Exception):
    """Raised when gift audio storage in Cloudflare R2 fails."""


_R2_ENDPOINT = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
_R2_CLIENT = boto3.client(
    "s3",
    endpoint_url=_R2_ENDPOINT,
    region_name="auto",
    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
)

_ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ("mp3", "audio/mpeg"),
    "audio/mp3": ("mp3", "audio/mpeg"),
    "audio/wav": ("wav", "audio/wav"),
    "audio/x-wav": ("wav", "audio/wav"),
    "audio/wave": ("wav", "audio/wav"),
    "audio/vnd.wave": ("wav", "audio/wav"),
    "audio/ogg": ("ogg", "audio/ogg"),
    "application/ogg": ("ogg", "audio/ogg"),
    "audio/webm": ("webm", "audio/webm"),
    "video/webm": ("webm", "audio/webm"),
}


def _detect_audio_type(file_bytes: bytes) -> tuple[str, str]:
    if not file_bytes:
        raise R2StorageError("Audio file is empty.")
    try:
        detected_mime = magic.from_buffer(file_bytes, mime=True)
    except Exception as exc:
        raise R2StorageError("Unable to determine the uploaded audio format.") from exc
    detected = _ALLOWED_AUDIO_TYPES.get(detected_mime)
    if detected is None:
        raise R2StorageError("Unsupported audio format. Use MP3, WAV, OGG, or WebM audio.")
    return detected


def _upload_object(key: str, file_bytes: bytes, content_type: str) -> None:
    try:
        _R2_CLIENT.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        raise R2StorageError("Failed to upload audio to Cloudflare R2.") from exc


def _delete_object(key: str) -> None:
    try:
        _R2_CLIENT.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise R2StorageError("Failed to delete audio from Cloudflare R2.") from exc


def is_owned_gift_audio_url(url: str | None, user_id: int) -> bool:
    if not url:
        return False
    expected = urlparse(settings.R2_PUBLIC_BASE_URL.rstrip("/"))
    parsed = urlparse(url)
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        return False
    return parsed.path.lstrip("/").startswith(f"gift-alerts/{user_id}-")


async def upload_gift_audio(file_bytes: bytes, user_id: int) -> str:
    extension, content_type = _detect_audio_type(file_bytes)
    key = f"gift-alerts/{user_id}-{uuid4().hex}.{extension}"
    await asyncio.to_thread(_upload_object, key, file_bytes, content_type)
    return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"


async def delete_gift_audio(url: str) -> None:
    expected = urlparse(settings.R2_PUBLIC_BASE_URL.rstrip("/"))
    parsed = urlparse(url)
    if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
        raise R2StorageError("Refusing to delete an audio URL outside the configured R2 public base URL.")
    key = parsed.path.lstrip("/")
    if not key.startswith("gift-alerts/"):
        raise R2StorageError("Refusing to delete a non-gift audio object.")
    await asyncio.to_thread(_delete_object, key)
