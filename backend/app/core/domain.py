from datetime import UTC, date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.errors import ApplicationError

Cents = Annotated[int, Field(strict=True, gt=0, le=2_000_000_000)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Reason = Annotated[str, Field(min_length=3, max_length=500)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetime(cls, value):
        # SQLite returns naive timestamps; all persisted timestamps are UTC.
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class ReasonRequest(Input):
    reason: Reason


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_today() -> date:
    return datetime.now(ZoneInfo("America/Fortaleza")).date()


def required(value, label: str):
    if value is None:
        raise ApplicationError("not_found", f"{label} não encontrado(a).", 404)
    return value
