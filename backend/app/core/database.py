from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings


def build_engine(url: URL) -> Engine:
    if url.get_backend_name() == "sqlite":
        return create_engine(
            url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"check_same_thread": False, "timeout": 5},
        )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=5,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
