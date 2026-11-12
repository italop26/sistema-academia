from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, field_validator, model_validator

from app.core.domain import Cents, Input, Output


class SimulatedEvent(Input):
    schema_version: int = Field(strict=True, ge=1, le=1)
    event_id: UUID
    event_type: Literal["payment.confirmed", "charge.pending", "charge.cancelled"]
    is_simulated: StrictBool
    charge_id: UUID
    reference: str = Field(min_length=1, max_length=128)
    amount_cents: Cents
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    external_payment_id: str | None = Field(
        None, min_length=10, max_length=128, pattern=r"^TEST-PAY-[A-Za-z0-9-]+$"
    )
    occurred_at: AwareDatetime

    @field_validator("occurred_at")
    @classmethod
    def utc_occurrence(cls, value: datetime):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_envelope(self):
        if not self.is_simulated:
            raise ValueError("Somente eventos simulados são aceitos")
        if (self.event_type == "payment.confirmed") != (self.external_payment_id is not None):
            raise ValueError("Referência de pagamento obrigatória apenas na confirmação")
        return self


class EventPublic(Output):
    id: str
    provider: str
    external_event_id: str
    payload: dict
    status: Literal["received", "processed", "ignored", "rejected", "failed"]
    attempt_count: int
    delivery_count: int
    conflict_count: int
    last_error_code: str | None
    result_code: str | None
    charge_id: str | None
    payment_id: str | None
    received_at: datetime
    last_received_at: datetime
    last_attempt_at: datetime | None
    processed_at: datetime | None


class EventReceipt(Output):
    id: str
    external_event_id: str
    status: str
    duplicate: bool
    is_simulated: Literal[True] = True
    simulation_notice: str
    error_code: str | None
