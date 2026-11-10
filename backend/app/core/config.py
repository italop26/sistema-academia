from functools import lru_cache
from typing import Literal
from urllib.parse import quote, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str | None = None
    postgres_user: str | None = None
    postgres_password: SecretStr | None = Field(default=None, min_length=1)
    database_url_input: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_password: SecretStr = Field(min_length=1)
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_access_token_minutes: int = Field(default=15, ge=1, le=60)
    jwt_issuer: str = "academia-api"
    jwt_audience: str = "academia-client"

    @field_validator("database_url_input", mode="before")
    @classmethod
    def empty_database_url(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_database(self):
        if self.database_url_input:
            try:
                url = make_url(self.database_url_input.get_secret_value())
                if url.drivername not in {"sqlite", "sqlite+pysqlite", "postgresql+psycopg"}:
                    raise ValueError
                if url.get_backend_name() == "sqlite" and (url.host or url.username):
                    raise ValueError
            except Exception as exc:
                raise ValueError("DATABASE_URL deve usar SQLite ou PostgreSQL com psycopg") from exc
        elif not all((self.postgres_db, self.postgres_user, self.postgres_password)):
            raise ValueError("Configure DATABASE_URL ou as credenciais PostgreSQL")
        return self

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or "*" in origin
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError("CORS exige origens HTTP(S) explícitas, sem caminho ou curinga")
        return origins

    @property
    def database_url(self) -> URL:
        if self.database_url_input:
            return make_url(self.database_url_input.get_secret_value())
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value() if self.postgres_password else None,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    def redis_url(self, database: int = 0) -> str:
        password = quote(self.redis_password.get_secret_value(), safe="")
        return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{database}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
