from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, field_validator

from app.core.domain import Input, Name, Output, ReasonRequest
from app.modules.users.schemas import normalize_email


class StudentCreate(Input):
    name: Name
    email: EmailStr | None = None
    user_id: UUID | None = None

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, value):
        return normalize_email(value) if isinstance(value, str) else value


class StudentPublic(Output):
    id: str
    name: str
    email: str | None
    user_id: str | None
    is_active: bool
    created_at: datetime


Deactivate = ReasonRequest
