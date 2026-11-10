import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings

password_hasher = PasswordHash.recommended()
# Faz a verificação de senha também quando o e-mail não existe.
DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password, password_hash)
    except (UnknownHashError, ValueError):
        return False


def create_access_token(user_id: str) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.jwt_access_token_minutes)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + lifetime,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": uuid4().hex,
        "token_type": "access",
    }
    return (
        jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm="HS256"),
        int(lifetime.total_seconds()),
    )


def decode_access_token_claims(token: str) -> dict:
    settings = get_settings()
    if len(token) > 8192:
        raise jwt.InvalidTokenError("Token inválido")
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "iat", "exp", "iss", "aud", "jti", "token_type"]},
    )
    if payload["token_type"] != "access":
        raise jwt.InvalidTokenError("Tipo de token inválido")
    try:
        payload["sub"] = str(UUID(payload["sub"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise jwt.InvalidTokenError("Identidade inválida") from exc
    return payload


def decode_access_token(token: str) -> str:
    return decode_access_token_claims(token)["sub"]
