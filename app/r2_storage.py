import asyncio
from urllib.parse import urlparse
from uuid import uuid4

import boto3
import magic
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings


class R2StorageError(Exception):
    """Raised when Cloudflare R2 storage fails."""


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


_ALLOWED_IMAGE_TYPES = {
    "image/webp": ("webp", "image/webp"),
    "image/png": ("png", "image/png"),
    "image/jpeg": ("jpg", "image/jpeg"),
}


def _detect_audio_type(file_bytes: bytes) -> tuple[str, str]:
    if not file_bytes:
        raise R2StorageError("Audio file is empty.")

    try:
        detected_mime = magic.from_buffer(file_bytes, mime=True)
    except Exception as exc:
        raise R2StorageError(
            "Unable to determine the uploaded audio format."
        ) from exc

    detected = _ALLOWED_AUDIO_TYPES.get(detected_mime)

    if detected is None:
        raise R2StorageError(
            "Unsupported audio format. Use MP3, WAV, OGG, or WebM audio."
        )

    return detected


def _detect_image_type(file_bytes: bytes) -> tuple[str, str]:
    if not file_bytes:
        raise R2StorageError("Image file is empty.")

    try:
        detected_mime = magic.from_buffer(file_bytes, mime=True)
    except Exception as exc:
        raise R2StorageError(
            "Unable to determine the uploaded image format."
        ) from exc

    detected = _ALLOWED_IMAGE_TYPES.get(detected_mime)

    if detected is None:
        raise R2StorageError(
            "Unsupported image format. Use PNG, JPEG, or WebP."
        )

    return detected


def _put_object(
    key: str,
    file_bytes: bytes,
    content_type: str,
) -> None:
    try:
        _R2_CLIENT.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        raise R2StorageError(
            "Failed to upload object to Cloudflare R2."
        ) from exc


def _delete_object(key: str) -> None:
    try:
        _R2_CLIENT.delete_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise R2StorageError(
            "Failed to delete object from Cloudflare R2."
        ) from exc


def _get_object(key: str) -> bytes:
    try:
        response = _R2_CLIENT.get_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
        )
        return response["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise R2StorageError(
            "Failed to download object from Cloudflare R2."
        ) from exc


def _object_exists(key: str) -> bool:
    try:
        _R2_CLIENT.head_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
        )
        return True

    except ClientError as exc:
        error_code = str(
            exc.response.get("Error", {}).get("Code", "")
        )

        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return False

        raise R2StorageError(
            "Failed to check Cloudflare R2 object."
        ) from exc

    except BotoCoreError as exc:
        raise R2StorageError(
            "Failed to check Cloudflare R2 object."
        ) from exc


def _key_from_url(url: str) -> str:
    expected = urlparse(
        settings.R2_PUBLIC_BASE_URL.rstrip("/")
    )
    parsed = urlparse(url)

    if (
        parsed.scheme != expected.scheme
        or parsed.netloc != expected.netloc
    ):
        raise R2StorageError(
            "Object URL is outside the configured R2 public base URL."
        )

    key = parsed.path.lstrip("/")

    if not key:
        raise R2StorageError(
            "Object URL does not contain an object key."
        )

    return key


async def upload_audio(
    file_bytes: bytes,
    *,
    owner_user_id: int | None,
    name: str,
) -> tuple[str, str]:
    extension, content_type = _detect_audio_type(file_bytes)

    namespace = (
        "system-sounds"
        if owner_user_id is None
        else f"user-sounds/{owner_user_id}"
    )

    key = f"{namespace}/{uuid4().hex}.{extension}"

    await asyncio.to_thread(
        _put_object,
        key,
        file_bytes,
        content_type,
    )

    return (
        key,
        f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}",
    )


async def upload_gift_audio(
    file_bytes: bytes,
    user_id: int,
) -> str:
    key, url = await upload_audio(
        file_bytes,
        owner_user_id=user_id,
        name="gift-alert",
    )

    return url


async def upload_gift_image(
    file_bytes: bytes,
    *,
    gift_id: str,
    extension: str,
    content_type: str,
) -> str:
    """
    Upload a gift image using a deterministic Euler gift ID.

    Example:
        gift-images/5269.webp
        gift-images/5333.webp
        gift-images/generic-tiktok.png
    """

    if not file_bytes:
        raise R2StorageError("Gift image is empty.")

    extension = extension.lower().lstrip(".")

    allowed = {
        "webp": "image/webp",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }

    expected_content_type = allowed.get(extension)

    if expected_content_type is None:
        raise R2StorageError(
            "Unsupported gift image extension."
        )

    if content_type != expected_content_type:
        raise R2StorageError(
            "Gift image extension and content type do not match."
        )

    key = f"gift-images/{gift_id}.{extension}"

    await asyncio.to_thread(
        _put_object,
        key,
        file_bytes,
        content_type,
    )

    return (
        f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    )


async def gift_image_exists(
    *,
    gift_id: str,
    extension: str,
) -> bool:
    extension = extension.lower().lstrip(".")

    key = f"gift-images/{gift_id}.{extension}"

    return await asyncio.to_thread(
        _object_exists,
        key,
    )


async def upload_generic_gift_image(
    file_bytes: bytes,
    *,
    extension: str,
    content_type: str,
) -> str:
    """
    Upload the shared generic TikTok fallback image.

    This uses one deterministic R2 object instead of creating
    a duplicate copy for every gift.
    """

    if not file_bytes:
        raise R2StorageError(
            "Generic gift image is empty."
        )

    extension = extension.lower().lstrip(".")

    allowed = {
        "webp": "image/webp",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }

    expected_content_type = allowed.get(extension)

    if expected_content_type is None:
        raise R2StorageError(
            "Unsupported generic gift image extension."
        )

    if content_type != expected_content_type:
        raise R2StorageError(
            "Generic gift image extension and content type do not match."
        )

    key = f"gift-images/generic-tiktok.{extension}"

    exists = await asyncio.to_thread(
        _object_exists,
        key,
    )

    if not exists:
        await asyncio.to_thread(
            _put_object,
            key,
            file_bytes,
            content_type,
        )

    return (
        f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    )


async def delete_audio_key(key: str) -> None:
    await asyncio.to_thread(
        _delete_object,
        key,
    )


async def delete_gift_audio(url: str) -> None:
    key = _key_from_url(url)

    if not key.startswith("gift-alerts/") and not key.startswith(
        "user-sounds/"
    ):
        raise R2StorageError(
            "Refusing to delete a non-user audio object."
        )

    await delete_audio_key(key)


async def download_audio_key(key: str) -> bytes:
    return await asyncio.to_thread(
        _get_object,
        key,
    )


def is_owned_gift_audio_url(
    url: str | None,
    user_id: int,
) -> bool:
    if not url:
        return False

    try:
        key = _key_from_url(url)
    except R2StorageError:
        return False

    return (
        key.startswith(f"user-sounds/{user_id}/")
        or key.startswith(f"gift-alerts/{user_id}-")
    )