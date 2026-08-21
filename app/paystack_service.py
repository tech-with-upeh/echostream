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

    if not response.content:
        raise PaystackError(
            f"Paystack request failed with HTTP {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise PaystackError(
            f"Paystack returned invalid JSON (HTTP {response.status_code})"
        ) from exc

    if response.is_error:
        raise PaystackError(
            data.get("message")
            or f"Paystack request failed (HTTP {response.status_code})"
        )

    if not data.get("status"):
        raise PaystackError(
            data.get("message") or "Paystack request was unsuccessful"
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


async def verify_transaction(reference: str) -> dict[str, Any]:
    return await paystack_request(
        "GET",
        f"/transaction/verify/{reference}",
    )


# ---------------------------------------------------------------------------
# Paystack plans
# ---------------------------------------------------------------------------

async def create_plan(
    *,
    name: str,
    amount_naira: int,
    interval: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a Paystack subscription plan. Amount is in NGN kobo."""
    payload: dict[str, Any] = {
        "name": name,
        "amount": amount_naira * 100,
        "interval": interval,
        "currency": "NGN",
    }

    if description:
        payload["description"] = description

    return await paystack_request(
        "POST",
        "/plan",
        payload=payload,
    )


async def update_plan(
    plan_code: str,
    *,
    name: str | None = None,
    amount_naira: int | None = None,
    interval: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update an existing Paystack plan."""
    payload: dict[str, Any] = {}

    if name is not None:
        payload["name"] = name

    if amount_naira is not None:
        payload["amount"] = amount_naira * 100

    if interval is not None:
        payload["interval"] = interval

    if description is not None:
        payload["description"] = description

    return await paystack_request(
        "PUT",
        f"/plan/{plan_code}",
        payload=payload,
    )


async def list_plans(
    *,
    page: int = 1,
    per_page: int = 100,
) -> dict[str, Any]:
    return await paystack_request(
        "GET",
        "/plan",
        params={
            "page": page,
            "perPage": per_page,
        },
    )


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

async def fetch_customer(customer_code: str) -> dict[str, Any]:
    return await paystack_request(
        "GET",
        f"/customer/{customer_code}",
    )


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

async def fetch_subscription(subscription_code: str) -> dict[str, Any]:
    return await paystack_request(
        "GET",
        f"/subscription/{subscription_code}",
    )


async def fetch_customer_subscriptions(
    customer_id: int,
) -> dict[str, Any]:
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
    customer_response = await fetch_customer(customer_code)
    customer = customer_response.get("data") or {}
    customer_id = customer.get("id")

    if not customer_id:
        raise PaystackError(
            "Paystack customer response did not contain a customer ID"
        )

    return await fetch_customer_subscriptions(int(customer_id))


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

async def get_subscription_manage_link(
    subscription_code: str,
) -> dict[str, Any]:
    return await paystack_request(
        "GET",
        f"/subscription/{subscription_code}/manage/link",
    )


async def disable_subscription(
    subscription_code: str,
    email_token: str,
) -> dict[str, Any]:
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
# Plan helpers
# ---------------------------------------------------------------------------

def get_plan_code(
    plan: str,
    interval: str = "month",
) -> str:
    """Return the configured Paystack plan code for plan + billing period."""
    normalized_plan = plan.lower().strip()
    normalized_interval = interval.lower().strip()

    plan_codes = {
        ("essential", "month"): settings.PAYSTACK_ESSENTIAL_MONTHLY_PLAN_CODE
        or settings.PAYSTACK_ESSENTIAL_PLAN_CODE,
        ("essential", "year"): settings.PAYSTACK_ESSENTIAL_YEARLY_PLAN_CODE,
        ("pro", "month"): settings.PAYSTACK_PRO_MONTHLY_PLAN_CODE
        or settings.PAYSTACK_PRO_PLAN_CODE,
        ("pro", "year"): settings.PAYSTACK_PRO_YEARLY_PLAN_CODE,
    }

    try:
        plan_code = plan_codes[(normalized_plan, normalized_interval)]
    except KeyError as exc:
        raise PaystackError(
            f"Invalid subscription plan/interval: "
            f"{normalized_plan}/{normalized_interval}"
        ) from exc

    if not plan_code:
        raise PaystackError(
            f"Paystack plan code is not configured for: "
            f"{normalized_plan}/{normalized_interval}"
        )

    return plan_code
