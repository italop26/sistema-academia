from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.domain import Cents, Input, Output


class ChargeCreate(Input):
    monthly_fee_id: UUID
    idempotency_key: UUID
    expires_in_seconds: int = Field(3600, strict=True, ge=60, le=86400)


class SimulatedReceipt(Input):
    """Internal test helper; HTTP confirmations use the webhook event contract."""

    charge_id: UUID
    reference: str = Field(min_length=1, max_length=128)
    external_payment_id: str = Field(
        min_length=10, max_length=128, pattern=r"^TEST-PAY-[A-Za-z0-9-]+$"
    )
    amount_cents: Cents
    currency: Literal["BRL"] = "BRL"


class ChargePublic(Output):
    id: str
    monthly_fee_id: str
    provider: str
    reference: str
    idempotency_key: str
    amount_cents: int
    currency: str
    status: Literal["pending", "expired", "paid", "cancelled"]
    is_simulated: bool
    simulation_notice: str | None
    payment_code: None = None
    expires_at: datetime
    created_at: datetime
    created_by: str


class PaymentPublic(Output):
    # Existing manual response fields are retained; new metadata is additive.
    id: str
    monthly_fee_id: str
    amount_cents: int
    actor_id: str | None
    note: str
    paid_at: datetime
    method: Literal["manual", "pix"]
    currency: str
    charge_id: str | None
    provider: str | None
    external_payment_id: str | None
    is_simulated: bool
