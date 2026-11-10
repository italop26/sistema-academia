from jwt import InvalidTokenError

from app.core.errors import ApplicationError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    decode_access_token_claims,
    verify_password,
)
from app.modules.auth.repositories import TokenRepository
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.users.models import User
from app.modules.users.repositories import UserRepository


def unauthorized(message: str = "Autenticação necessária ou token inválido.") -> ApplicationError:
    return ApplicationError("unauthorized", message, 401, {"WWW-Authenticate": "Bearer"})


class AuthService:
    def __init__(self, repository: UserRepository, tokens: TokenRepository):
        self.repository = repository
        self.tokens = tokens

    def login(self, data: LoginRequest) -> TokenResponse:
        user = self.repository.get_by_email(str(data.email))
        password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
        valid = verify_password(data.password.get_secret_value(), password_hash)
        if not valid or user is None or not user.is_active:
            raise unauthorized("E-mail ou senha inválidos.")
        token, expires_in = create_access_token(user.id)
        return TokenResponse(access_token=token, expires_in=expires_in)

    def validate_token(self, token: str) -> dict:
        try:
            claims = decode_access_token_claims(token)
        except InvalidTokenError as exc:
            raise unauthorized() from exc
        if self.tokens.is_revoked(claims["jti"]):
            raise unauthorized()
        return claims

    def authenticate(self, token: str) -> User:
        claims = self.validate_token(token)
        user = self.repository.get_by_id(claims["sub"])
        if user is None or not user.is_active:
            raise unauthorized()
        return user

    def logout(self, token: str) -> None:
        claims = self.validate_token(token)
        self.tokens.revoke(claims["jti"], claims["exp"])
