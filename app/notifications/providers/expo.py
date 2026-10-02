from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


@dataclass
class ExpoPushResult:
    push_token: str
    ok: bool
    error_code: str | None = None  # e.g. "DeviceNotRegistered", "MessageTooBig"
    message: str | None = None


async def send_expo_push(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> list[ExpoPushResult]:
    """Send a push to one or more Expo push tokens.

    Returns one ExpoPushResult per token, in the same order as `tokens`,
    so callers can map failures back to devices.
    """
    if not tokens:
        return []

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if settings.EXPO_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.EXPO_ACCESS_TOKEN}"

    messages = [
        {
            "to": token,
            "title": title,
            "body": body,
            "data": data or {},
            "sound": "default",
        }
        for token in tokens
    ]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                settings.EXPO_PUSH_URL, json=messages, headers=headers
            )
    except httpx.HTTPError as exc:
        return [
            ExpoPushResult(push_token=t, ok=False, error_code="RequestFailed", message=str(exc))
            for t in tokens
        ]

    if response.status_code != 200:
        return [
            ExpoPushResult(
                push_token=t,
                ok=False,
                error_code="HTTPError",
                message=f"status={response.status_code} body={response.text}",
            )
            for t in tokens
        ]

    payload = response.json()
    tickets = payload.get("data", [])

    results: list[ExpoPushResult] = []
    for token, ticket in zip(tokens, tickets):
        if ticket.get("status") == "ok":
            results.append(ExpoPushResult(push_token=token, ok=True))
        else:
            details = ticket.get("details") or {}
            results.append(
                ExpoPushResult(
                    push_token=token,
                    ok=False,
                    error_code=details.get("error"),
                    message=ticket.get("message"),
                )
            )
    return results