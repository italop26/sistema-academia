import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError


def test_live_does_not_depend_on_external_services(client, dependencies):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    dependencies[0].execute.assert_not_called()
    dependencies[1].ping.assert_not_called()


def test_health_checks_dependencies(client, dependencies):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}
    assert str(dependencies[0].execute.call_args.args[0]) == "SELECT 1"
    dependencies[1].ping.assert_called_once()
    assert len(response.headers["X-Request-ID"]) == 32


@pytest.mark.parametrize("database_down,redis_down", [(True, False), (False, True), (True, True)])
def test_health_reports_service_failures(client, dependencies, database_down, redis_down):
    session, redis = dependencies
    if database_down:
        session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("secret"))
    if redis_down:
        redis.ping.side_effect = RedisConnectionError("secret")
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "unavailable" if database_down else "ok",
        "redis": "unavailable" if redis_down else "ok",
    }
    assert "secret" not in response.text


def test_unhandled_error_is_sanitized_and_has_cors(client, dependencies):
    dependencies[0].execute.side_effect = RuntimeError("sensitive-internal-data")
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "sensitive-internal-data" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_not_found_uses_error_contract(client):
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"


def test_validation_error_does_not_echo_inputs(client):
    @client.app.get("/validation-test")
    def validation_test(count: int):
        return count

    response = client.get("/validation-test?count=sensitive-input")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "sensitive-input" not in response.text


@pytest.mark.parametrize(
    "origin,allowed",
    [
        ("http://localhost:5173", True),
        ("https://untrusted.example", False),
    ],
)
def test_cors_preflight_is_restricted(client, origin, allowed):
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == (200 if allowed else 400)
    assert ("access-control-allow-origin" in response.headers) is allowed


def test_cors_does_not_authorize_unimplemented_methods(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert response.status_code == 400
