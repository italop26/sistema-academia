import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("origin", ["*", "https://*.example.com", "http://host/path"])
def test_cors_rejects_wildcards_and_paths(origin):
    with pytest.raises(ValidationError):
        Settings(cors_origins=[origin], _env_file=None)


def test_database_url_preserves_special_characters_in_password():
    settings = Settings(DATABASE_URL=None, postgres_password="a@b:/%x", _env_file=None)
    assert settings.database_url.password == "a@b:/%x"
    assert "a@b:/%x" not in repr(settings)


def test_redis_url_escapes_password():
    settings = Settings(redis_password="a@b:/%x", _env_file=None)
    assert ":a%40b%3A%2F%25x@" in settings.redis_url(1)
    assert settings.redis_url(1).endswith("/1")


def test_empty_password_is_rejected():
    with pytest.raises(ValidationError):
        Settings(postgres_password="", _env_file=None)


def test_celery_has_no_business_schedule():
    from app.core.celery_app import celery_app

    assert celery_app.conf.beat_schedule == {}
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.broker_url.endswith("/0")
    assert celery_app.conf.result_backend.endswith("/1")


def test_sqlite_does_not_require_postgres_credentials():
    settings = Settings(
        DATABASE_URL="sqlite+pysqlite:///./data/test.db",
        postgres_db=None,
        postgres_user=None,
        postgres_password=None,
        _env_file=None,
    )
    assert settings.database_url.get_backend_name() == "sqlite"


def test_weak_jwt_key_is_rejected():
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key="weak", _env_file=None)
