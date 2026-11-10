"""Contas descartáveis para testes; nunca executar no banco da aplicação."""

import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.security import hash_password
from app.modules.users.models import User, UserRole
from app.modules.users.repositories import UserRepository
from app.modules.users.schemas import AdminCreate
from app.modules.users.services import UserService


def main():
    settings = get_settings()
    if (
        os.getenv("VALIDATION_ONLY") != "1"
        or settings.app_env != "test"
        or settings.database_url.database != "./data/validation.db"
    ):
        raise SystemExit("O seed exige o ambiente isolado academia-validation.")
    path = Path("/app/data/e2e-credentials.json")
    if path.exists():
        print("Contas de teste existentes preservadas.")
        return
    password = secrets.token_urlsafe(24)
    with Session(get_engine()) as session:
        admin = UserService(UserRepository(session)).bootstrap_admin(
            AdminCreate(
                name="Administrador de teste",
                email="admin@example.com",
                password=password,
            )
        )
    with Session(get_engine()) as session, session.begin():
        session.add(
            User(
                name="Membro de teste",
                email="member@example.com",
                password_hash=hash_password(password),
                role=UserRole.MEMBER,
            )
        )
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": admin.id,
            "iat": now - timedelta(minutes=20),
            "exp": now - timedelta(minutes=5),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": uuid4().hex,
            "token_type": "access",
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(
            {
                "email": admin.email,
                "password": password,
                "member": "member@example.com",
                "expired": expired,
            },
            output,
        )
    print("Contas descartáveis preparadas; credenciais não exibidas.")


if __name__ == "__main__":
    main()
