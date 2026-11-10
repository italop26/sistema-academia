import os
import time

import pytest
from fastapi.testclient import TestClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION_TESTS") != "1",
        reason="Use docker compose run --rm tests para testar os serviços reais",
    ),
]


def test_health_with_real_postgres_and_redis():
    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


def test_worker_executes_infrastructure_task():
    from app.core.celery_app import celery_app

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if celery_app.control.ping(timeout=1):
            break
        time.sleep(1)
    else:
        pytest.fail("O worker não respondeu em 30 segundos")
    # Tarefa nativa do Celery; nenhum módulo de negócio é criado.
    result = celery_app.send_task("celery.backend_cleanup")
    try:
        result.get(timeout=20)
        assert result.successful()
    finally:
        result.forget()
