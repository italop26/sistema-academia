from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import build_engine, get_engine, get_session
from app.core.errors import ApplicationError
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password, verify_password
from app.main import create_app
from app.modules.auth.dependencies import require_admin
from app.modules.users.models import User, UserRole
from app.modules.users.repositories import UserRepository
from app.modules.users.schemas import AdminCreate
from app.modules.users.services import UserService

PASSWORD = "valid-test-password-2026"


@pytest.fixture
def sqlite_database(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = build_engine(get_settings().database_url)
    yield engine
    engine.dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def admin(sqlite_database):
    with Session(sqlite_database) as session:
        return UserService(UserRepository(session)).bootstrap_admin(
            AdminCreate(
                name="Administrador",
                email="admin@example.com",
                password=PASSWORD,
            )
        )


@pytest.fixture
def token_redis():
    redis = Mock()
    revoked = set()
    redis.exists.side_effect = lambda key: int(key in revoked)
    redis.set.side_effect = lambda key, value, exat: revoked.add(key) or True
    return redis


@pytest.fixture
def auth_client(sqlite_database, token_redis) -> Iterator[TestClient]:
    app = create_app()

    def session_dependency():
        with Session(sqlite_database) as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_redis] = lambda: token_redis

    @app.get("/test/admin", dependencies=[Depends(require_admin)])
    def admin_only():
        return {"status": "ok"}

    with TestClient(app) as client:
        yield client


def login(client, email="admin@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_login_and_me(auth_client, admin):
    response = login(auth_client, email=" ADMIN@EXAMPLE.COM ")
    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"
    assert token["expires_in"] == get_settings().jwt_access_token_minutes * 60
    assert response.headers["cache-control"] == "no-store"
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    response = auth_client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == admin.id
    assert data["email"] == "admin@example.com"
    assert data["role"] == "admin"
    assert data["is_active"] is True
    assert data["created_at"].endswith("Z")
    assert "password" not in response.text
    assert auth_client.get("/test/admin", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "email,password",
    [
        ("admin@example.com", "incorrect"),
        ("missing@example.com", PASSWORD),
    ],
)
def test_invalid_credentials_are_generic(auth_client, admin, email, password):
    response = login(auth_client, email, password)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "E-mail ou senha inválidos."
    assert response.headers["www-authenticate"] == "Bearer"
    assert password not in response.text


@pytest.mark.parametrize("authorization", [None, "Basic abc", "Bearer invalid", "Bearer"])
def test_unauthorized_me(auth_client, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = auth_client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "wrong-key",
        "wrong-issuer",
        "wrong-audience",
        "missing-exp",
        "invalid-sub",
        "wrong-type",
        "wrong-algorithm",
        "missing-iat",
    ],
)
def test_rejects_invalid_tokens(auth_client, admin, change):
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": admin.id,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": uuid4().hex,
        "token_type": "access",
    }
    key = settings.jwt_secret_key.get_secret_value()
    algorithm = "HS256"
    if change == "expired":
        payload["exp"] = now - timedelta(seconds=5)
    elif change == "wrong-key":
        key = "another-test-key-with-at-least-32-characters"
    elif change == "wrong-issuer":
        payload["iss"] = "untrusted"
    elif change == "wrong-audience":
        payload["aud"] = "other-client"
    elif change == "missing-exp":
        del payload["exp"]
    elif change == "missing-iat":
        del payload["iat"]
    elif change == "invalid-sub":
        payload["sub"] = "not-a-uuid"
    elif change == "wrong-type":
        payload["token_type"] = "refresh"
    elif change == "wrong-algorithm":
        algorithm = "HS384"
    token = jwt.encode(payload, key, algorithm=algorithm)
    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_disabled_user_cannot_login_or_keep_access(auth_client, admin, sqlite_database):
    token = login(auth_client).json()["access_token"]
    with Session(sqlite_database) as session, session.begin():
        session.get(User, admin.id).is_active = False
    assert login(auth_client).status_code == 401
    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_for_deleted_user_is_rejected(auth_client, admin, sqlite_database):
    token = login(auth_client).json()["access_token"]
    with Session(sqlite_database) as session, session.begin():
        session.delete(session.get(User, admin.id))
    assert (
        auth_client.get(
            "/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
            },
        ).status_code
        == 401
    )


def test_permission_uses_current_database_role(auth_client, admin, sqlite_database):
    token = login(auth_client).json()["access_token"]
    with Session(sqlite_database) as session, session.begin():
        session.get(User, admin.id).role = UserRole.MEMBER
    headers = {"Authorization": f"Bearer {token}"}
    assert auth_client.get("/auth/me", headers=headers).status_code == 200
    response = auth_client.get("/test/admin", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "invalid", "password": PASSWORD},
        {"email": 123, "password": PASSWORD},
        {"email": "admin@example.com", "password": ""},
        {"email": "admin@example.com", "password": "x" * 129},
        {"email": "admin@example.com", "password": PASSWORD, "role": "admin"},
    ],
)
def test_login_validates_input(auth_client, body):
    response = auth_client.post("/auth/login", json=body)
    assert response.status_code == 422
    assert PASSWORD not in response.text


def test_no_public_registration(auth_client):
    for path in ("/auth/register", "/users", "/users/admin"):
        assert auth_client.post(path, json={"role": "admin"}).status_code == 404


def test_cors_allows_login_and_bearer_header(auth_client):
    response = auth_client.options(
        "/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_admin_password_is_hashed(sqlite_database, admin):
    with Session(sqlite_database) as session:
        user = session.get(User, admin.id)
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != PASSWORD
        assert verify_password(PASSWORD, user.password_hash)
        assert not verify_password("invalid", user.password_hash)


def test_invalid_stored_hash_does_not_cause_internal_error(auth_client, admin, sqlite_database):
    with Session(sqlite_database) as session, session.begin():
        session.get(User, admin.id).password_hash = "invalid-hash"
    assert login(auth_client).status_code == 401


def test_email_is_unique_in_database(sqlite_database, admin):
    with Session(sqlite_database) as session:
        session.add(
            User(
                name="Duplicado",
                email=admin.email,
                password_hash="not-used",
                role=UserRole.MEMBER,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_concurrent_bootstrap_creates_only_one_admin(sqlite_database):
    def bootstrap(index):
        with Session(sqlite_database) as session:
            try:
                UserService(UserRepository(session)).bootstrap_admin(
                    AdminCreate(
                        name="Admin",
                        email=f"admin{index}@example.com",
                        password=PASSWORD,
                    )
                )
                return "created"
            except ApplicationError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(bootstrap, range(2)))
    assert sorted(results) == ["admin_exists", "created"]
    with Session(sqlite_database) as session:
        assert len(session.scalars(select(User)).all()) == 1


def test_bootstrap_cannot_create_second_admin(sqlite_database, admin):
    with Session(sqlite_database) as session:
        with pytest.raises(ApplicationError, match="já foi cadastrado"):
            UserService(UserRepository(session)).bootstrap_admin(
                AdminCreate(
                    name="Segundo",
                    email="other@example.com",
                    password=PASSWORD,
                )
            )
        assert len(session.scalars(select(User)).all()) == 1


def test_hash_uses_random_salt():
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_migration_upgrade_downgrade_and_metadata(sqlite_database):
    assert "users" in inspect(sqlite_database).get_table_names()
    config = Config("alembic.ini")
    command.check(config)
    command.downgrade(config, "base")
    assert "users" not in inspect(sqlite_database).get_table_names()
    command.upgrade(config, "head")
    assert "users" in inspect(sqlite_database).get_table_names()


def test_cli_creates_admin_without_exposing_password(sqlite_database, monkeypatch, capsys):
    from app.modules.users import cli

    monkeypatch.setattr(cli.sys, "stdin", Mock(isatty=lambda: True))
    values = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(values))
    monkeypatch.setattr(cli, "get_engine", lambda: sqlite_database)
    code = cli.main(["--name", "Admin", "--email", "admin@example.com"])
    output = capsys.readouterr()
    assert code == 0
    assert "cadastrado" in output.out
    assert PASSWORD not in output.out + output.err
    with Session(sqlite_database) as session:
        user = session.scalar(select(User))
        assert user.role == UserRole.ADMIN
        assert verify_password(PASSWORD, user.password_hash)


def test_cli_rejects_noninteractive_input(monkeypatch, capsys):
    from app.modules.users import cli

    monkeypatch.setattr(cli.sys, "stdin", Mock(isatty=lambda: False))
    assert cli.main(["--name", "Admin", "--email", "admin@example.com"]) == 1
    assert "terminal interativo" in capsys.readouterr().err


def test_cli_rejects_password_mismatch(sqlite_database, monkeypatch, capsys):
    from app.modules.users import cli

    monkeypatch.setattr(cli.sys, "stdin", Mock(isatty=lambda: True))
    values = iter([PASSWORD, "different"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(values))
    assert cli.main(["--name", "Admin", "--email", "admin@example.com"]) == 1
    assert "não coincidem" in capsys.readouterr().err
    with Session(sqlite_database) as session:
        assert session.scalar(select(User)) is None


def test_nonexistent_user_token_is_rejected(auth_client):
    token, _ = create_access_token(str(uuid4()))
    assert (
        auth_client.get(
            "/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
            },
        ).status_code
        == 401
    )


def test_logout_revokes_token(auth_client, admin, token_redis):
    token = login(auth_client).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert auth_client.get("/auth/admin", headers=headers).status_code == 200
    assert auth_client.post("/auth/logout", headers=headers).status_code == 204
    assert auth_client.get("/auth/me", headers=headers).status_code == 401
    assert auth_client.get("/auth/admin", headers=headers).status_code == 401
    assert token_redis.set.call_args.kwargs["exat"] > datetime.now(UTC).timestamp()


def test_admin_endpoint_checks_role(auth_client, admin, sqlite_database):
    token = login(auth_client).json()["access_token"]
    with Session(sqlite_database) as session, session.begin():
        session.get(User, admin.id).role = UserRole.MEMBER
    assert (
        auth_client.get("/auth/admin", headers={"Authorization": f"Bearer {token}"}).status_code
        == 403
    )


def test_auth_fails_closed_if_redis_is_down(auth_client, admin, token_redis):
    token = login(auth_client).json()["access_token"]
    token_redis.exists.side_effect = RedisConnectionError("sensitive-redis-data")
    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503
    assert "sensitive-redis-data" not in response.text


def test_logout_does_not_claim_success_if_redis_fails(auth_client, admin, token_redis):
    token = login(auth_client).json()["access_token"]
    token_redis.set.side_effect = RedisConnectionError("sensitive-redis-data")
    response = auth_client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503


def test_request_logs_do_not_expose_secrets(auth_client, admin, capsys):
    from app.core.logging import configure_logging

    configure_logging(get_settings().log_level)
    token = login(auth_client).json()["access_token"]
    auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    auth_client.get(f"/missing/{token}?password={PASSWORD}")
    captured = capsys.readouterr()
    logs = captured.out + captured.err
    assert "Requisição HTTP" in logs
    assert PASSWORD not in logs
    assert token not in logs
