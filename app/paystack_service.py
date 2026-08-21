import hashlib
import hmac
import json
from typing import Any, Optional

import httpx

from app.config import settings


PAYSTACK_BASE_URL = "https://api.paystack.co"


class PaystackError(Exception):
    """Raised when Paystack rejects an API request or is unavailable."""


async def paystack_request(
    method: str,
    path: str,
    *,
    payload: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        base_url=PAYSTACK_BASE_URL,
        timeout=20.0,
    ) as client:
        response = await client.request(
            method,
            path,
            json=payload,
            params=params,
            headers=headers,
        )

    # Paystack can return an empty response body on some errors.
    if not response.content:
        raise PaystackError(
            f"Paystack request failed with HTTP {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise PaystackError(
            f"Paystack returned invalid JSON "
            f"(HTTP {response.status_code})"
        ) from exc

    if response.is_error:
        raise PaystackError(
            data.get("message")
            or f"Paystack request failed "
            f"(HTTP {response.status_code})"
        )

    if not data.get("status"):
        raise PaystackError(
            data.get("message")
            or "Paystack request was unsuccessful"
        )

    return data


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

async def initialize_transaction(
    *,
    email: str,
    plan_code: str,
    reference: str,
    callback_url: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
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


async def verify_transaction(
    reference: str,
) -> dict[str, Any]:
    return await paystack_request(
        "GET",
        f"/transaction/verify/{reference}",
    )


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

async def fetch_customer(
    customer_code: str,
) -> dict[str, Any]:
    """
    Fetch a Paystack customer using their customer code.

    Example:
        CUS_lg7tzeyblao253p
    """

    return await paystack_request(
        "GET",
        f"/customer/{customer_code}",
    )


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

async def fetch_subscription(
    subscription_code: str,
) -> dict[str, Any]:
    """
    Fetch a single Paystack subscription.

    Example:
        SUB_xxxxxxxxx
    """

    return await paystack_request(
        "GET",
        f"/subscription/{subscription_code}",
    )


async def fetch_customer_subscriptions(
    customer_id: int,
) -> dict[str, Any]:
    """
    Fetch subscriptions belonging to a Paystack customer.

    Paystack's subscription listing endpoint expects the
    numeric customer ID, NOT the CUS_xxxxx customer code.

    Example:
        GET /subscription?customer=123456
    """

    return await paystack_request(
        "GET",
        "/subscription",
        params={
            "customer": customer_id,
            "perPage": 100,
            "page": 1,
        },
    )


async def fetch_customer_subscriptions_by_code(
    customer_code: str,
) -> dict[str, Any]:
    """
    Convenience helper.

    Resolves:

        CUS_xxxxx
             ↓
        Paystack customer ID
             ↓
        customer subscriptions

    This is useful because our database stores the customer_code,
    while Paystack's subscription listing endpoint expects the
    numeric customer ID.
    """

    customer_response = await fetch_customer(customer_code)

    customer = customer_response.get("data") or {}

    customer_id = customer.get("id")

    if not customer_id:
        raise PaystackError(
            "Paystack customer response did not contain a customer ID"
        )

    return await fetch_customer_subscriptions(
        int(customer_id)
    )


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

async def get_subscription_manage_link(
    subscription_code: str,
) -> dict[str, Any]:
    """
    Generate Paystack's hosted subscription management link.
    """

    return await paystack_request(
        "GET",
        f"/subscription/{subscription_code}/manage/link",
    )


async def disable_subscription(
    subscription_code: str,
    email_token: str,
) -> dict[str, Any]:
    """
    Disable/cancel a Paystack subscription.
    """

    return await paystack_request(
        "POST",
        "/subscription/disable",
        payload={
            "code": subscription_code,
            "token": email_token,
        },
    )


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def verify_webhook_signature(
    raw_body: bytes,
    signature: str,
) -> bool:
    """
    Verify Paystack webhook signature.

    Paystack signs the raw request body using HMAC SHA-512
    with the Paystack secret key.
    """

    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(
        expected,
        signature or "",
    )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def get_plan_code(
    plan: str,
) -> str:
    """
    Return the Paystack plan code configured for EchoStream.

    Starter intentionally has no Paystack plan because it is free.
    """

    plan_codes = {
        "essential": settings.PAYSTACK_ESSENTIAL_PLAN_CODE,
        "pro": settings.PAYSTACK_PRO_PLAN_CODE,
    }

    normalized_plan = plan.lower().strip()

    try:
        plan_code = plan_codes[normalized_plan]
    except KeyError as exc:
        raise PaystackError(
            f"Invalid paid subscription plan: {plan}"
        ) from exc

    if not plan_code:
        raise PaystackError(
            f"Paystack plan code is not configured for: {normalized_plan}"
        )

    return plan_code
