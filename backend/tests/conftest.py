import os
from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

# Valores isolados de teste; o Compose fornece as credenciais reais por ambiente.
for key, value in {
    "APP_ENV": "test",
    "POSTGRES_DB": "test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test-only",
    "REDIS_PASSWORD": "test-only",
    "JWT_SECRET_KEY": "isolated-test-signing-key-at-least-32-characters",
}.items():
    os.environ.setdefault(key, value)

from app.core.database import get_session  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def dependencies() -> tuple[Mock, Mock]:
    session = Mock()
    session.execute.return_value.scalar_one.return_value = 1
    redis = Mock()
    redis.ping.return_value = True
    return session, redis


@pytest.fixture
def client(dependencies) -> Iterator[TestClient]:
    session, redis = dependencies
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: redis
    with TestClient(app) as test_client:
        yield test_client
