import httpx
from urllib.parse import quote

from app.config import settings


class TikTokImageError(Exception):
    """Raised when a TikTok profile image cannot be fetched."""


async def fetch_tiktok_profile_image(unique_id: str) -> bytes:
    unique_id = unique_id.strip().lstrip("@")
    if not unique_id:
        raise TikTokImageError("TikTok username is not configured.")

    if not settings.EULER_GIFT_CATALOG_API_KEY:
        raise TikTokImageError("Euler Stream is not configured.")

    url = (
        f"{settings.EULER_GIFT_CATALOG_BASE_URL.rstrip('/')}"
        f"/tiktok/users/{quote(unique_id, safe='')}/basic"
    )
    headers = {"x-api-key": settings.EULER_GIFT_CATALOG_API_KEY}

    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TikTokImageError(
                "Failed to fetch the TikTok profile from Euler Stream."
            ) from exc

        user = payload.get("user") or {}
        image_url = next(
            (
                image
                for field in ("avatar_larger", "avatar_medium", "avatar_thumb")
                for image in (user.get(field) or [])
                if isinstance(image, str) and image.startswith(("http://", "https://"))
            ),
            None,
        )

        if not image_url:
            raise TikTokImageError(
                "Euler Stream did not return a TikTok profile image."
            )

        try:
            image_response = await client.get(image_url)
            image_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TikTokImageError(
                "Failed to download the TikTok profile image."
            ) from exc

        if not image_response.content:
            raise TikTokImageError("TikTok profile image is empty.")

        return image_response.content
