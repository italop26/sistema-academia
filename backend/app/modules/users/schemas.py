from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.modules.users.models import UserRole


def normalize_email(value: str) -> str:
    return value.strip().casefold()


class AdminCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return normalize_email(value) if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nome obrigatório")
        return value


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
