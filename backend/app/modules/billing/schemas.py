import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.core.domain import Cents, Input, Output, Reason
from app.modules.payments.schemas import PaymentPublic as PaymentPublic


def parse_competence(value: str) -> date:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("Competência deve usar AAAA-MM")
    return date.fromisoformat(f"{value}-01")


class GenerateFee(Input):
    enrollment_id: UUID
    competence: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @field_validator("competence")
    @classmethod
    def valid_competence(cls, value):
        parse_competence(value)
        return value


class PaymentCreate(Input):
    amount_cents: Cents
    note: Reason


class FeePublic(Output):
    id: str
    enrollment_id: str
    student_id: str
    student_name: str
    competence: str
    due_on: date
    amount_cents: int
    status: Literal["pendente", "vencida", "paga", "cancelada"]
    completed: bool
    paid_at: datetime | None
    created_at: datetime

    payment_method: Literal["manual", "pix"] | None = None
    is_simulated: bool = False
    simulation_notice: str | None = None
