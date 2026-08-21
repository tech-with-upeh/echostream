import hashlib
import hmac
import json
from typing import Any, Optional

import httpx

from app.config import settings

PAYSTACK_BASE_URL = "https://api.paystack.co"


class PaystackError(Exception):
    """Raised when Paystack rejects an API request or is unavailable."""


async def paystack_request(method: str, path: str, *, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=PAYSTACK_BASE_URL, timeout=20.0) as client:
        response = await client.request(method, path, json=payload, headers=headers)
    try:
        data = response.json()
    except ValueError as exc:
        raise PaystackError("Paystack returned an invalid response") from exc
    if response.is_error or not data.get("status"):
        raise PaystackError(data.get("message") or "Paystack request failed")
    return data


async def initialize_transaction(*, email: str, plan_code: str, reference: str, callback_url: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return await paystack_request(
        "POST",
        "/transaction/initialize",
        payload={
            "email": email,
            "plan": plan_code,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": json.dumps(metadata),
        },
    )


async def verify_transaction(reference: str) -> dict[str, Any]:
    return await paystack_request("GET", f"/transaction/verify/{reference}")


async def fetch_subscription(subscription_code: str) -> dict[str, Any]:
    return await paystack_request("GET", f"/subscription/{subscription_code}")


async def disable_subscription(subscription_code: str, email_token: str) -> dict[str, Any]:
    return await paystack_request("POST", "/subscription/disable", payload={"code": subscription_code, "token": email_token})


async def get_subscription_manage_link(subscription_code: str) -> dict[str, Any]:
    return await paystack_request("GET", f"/subscription/{subscription_code}/manage/link")


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def get_plan_code(plan: str) -> str:
    plan_codes = {
        "essential": settings.PAYSTACK_ESSENTIAL_PLAN_CODE,
        "pro": settings.PAYSTACK_PRO_PLAN_CODE,
    }
    try:
        return plan_codes[plan.lower()]
    except KeyError as exc:
        raise PaystackError("Invalid paid subscription plan") from exc
