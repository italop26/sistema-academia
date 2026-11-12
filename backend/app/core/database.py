from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApplicationError


def build_engine(url: URL) -> Engine:
    if url.get_backend_name() == "sqlite":
        engine = create_engine(
            url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"check_same_thread": False, "timeout": 5},
        )
        event.listen(engine, "connect", enable_sqlite_foreign_keys)
        return engine
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


def enable_sqlite_foreign_keys(connection, _record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_business_session() -> Generator[Session, None, None]:
    # Separate dependency: authentication has already read using get_session().
    # Business services own their transaction from its first read through commit.
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


@contextmanager
def write_transaction(session: Session):
    try:
        with session.begin():
            if session.get_bind().dialect.name == "sqlite":
                # SQLite has no row-level FOR UPDATE. Serialize writers before reading state.
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield
    except IntegrityError as exc:
        raise ApplicationError(
            "record_conflict", "Registro duplicado ou relacionamento inválido.", 409
        ) from exc
    except OperationalError as exc:
        if session.get_bind().dialect.name == "sqlite" and "locked" in str(exc.orig).lower():
            raise ApplicationError("database_busy", "Banco ocupado. Tente novamente.", 503) from exc
        raise
