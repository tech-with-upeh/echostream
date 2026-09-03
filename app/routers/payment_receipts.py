from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models import DBPaymentHistory, DBUser
from app.schemas import (
    PaymentReceiptCustomer,
    PaymentReceiptPayment,
    PaymentReceiptResponse,
    PaymentReceiptSubscription,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


def add_billing_period(start: datetime, interval: str | None) -> datetime | None:
    if not start or interval not in {"month", "year"}:
        return None
    if interval == "year":
        try:
            return start.replace(year=start.year + 1)
        except ValueError:
            return start.replace(year=start.year + 1, day=28)

    month = start.month + 1
    year = start.year
    if month > 12:
        month = 1
        year += 1
    days = [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return start.replace(year=year, month=month, day=min(start.day, days[month - 1]))


@router.get("/history/{payment_id}/receipt", response_model=PaymentReceiptResponse)
async def get_payment_receipt(
    payment_id: str,
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DBPaymentHistory).where(
            DBPaymentHistory.user_id == current_user.id,
            DBPaymentHistory.payment_id == payment_id,
        )
    )
    payment = result.scalar_one_or_none()

    # Keep the endpoint compatible with the frontend's existing numeric history IDs.
    if payment is None and payment_id.isdigit():
        result = await db.execute(
            select(DBPaymentHistory).where(
                DBPaymentHistory.user_id == current_user.id,
                DBPaymentHistory.id == int(payment_id),
            )
        )
        payment = result.scalar_one_or_none()

    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    paid_at = payment.paid_at
    starts_at = paid_at
    ends_at = add_billing_period(paid_at, payment.interval) if paid_at else None

    method = payment.method
    if not method:
        channel = (payment.channel or "").lower()
        method = channel if channel else None

    return PaymentReceiptResponse(
        customer=PaymentReceiptCustomer(
            name=f"{current_user.first_name} {current_user.last_name}".strip(),
            email=current_user.email,
        ),
        payment=PaymentReceiptPayment(
            payment_id=payment.payment_id,
            receipt_number=payment.receipt_number,
            provider=payment.provider,
            provider_reference=payment.provider_reference,
            plan=payment.plan,
            interval=payment.interval,
            billing_type=payment.billing_type,
            method=method,
            amount=payment.amount,
            currency=payment.currency,
            status=payment.status,
            paid_at=payment.paid_at,
        ),
        subscription=PaymentReceiptSubscription(
            starts_at=starts_at,
            ends_at=ends_at,
        ),
        issued_at=datetime.now(timezone.utc),
    )
