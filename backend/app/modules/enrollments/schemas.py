from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.core.domain import Input, Output, Reason


class EnrollmentCreate(Input):
    student_id: UUID
    plan_id: UUID
    starts_on: date
    ends_on: date | None = None
    due_day: int = Field(strict=True, ge=1, le=31)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("Encerramento anterior ao início")
        return self


class EnrollmentPublic(Output):
    id: str
    student_id: str
    plan_id: str
    starts_on: date
    ends_on: date | None
    due_day: int
    amount_cents: int
    status: Literal["ativa", "cancelada"]
    created_at: datetime


class SuspensionCreate(Input):
    request_key: UUID
    reason: Reason


class SuspensionPublic(Output):
    id: str
    enrollment_id: str
    starts_at: datetime
    ends_at: datetime | None
    actor_id: str
    reason: str
