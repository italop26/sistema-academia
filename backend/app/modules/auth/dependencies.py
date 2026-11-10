from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.errors import ApplicationError
from app.core.redis import get_redis
from app.modules.auth.repositories import TokenRepository
from app.modules.auth.services import AuthService, unauthorized
from app.modules.users.models import User, UserRole
from app.modules.users.repositories import UserRepository

bearer = HTTPBearer(auto_error=False)


def get_auth_service(
    session: Annotated[Session, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> AuthService:
    return AuthService(UserRepository(session), TokenRepository(redis))


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None:
        raise unauthorized()
    return service.authenticate(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise ApplicationError("forbidden", "Permissão de administrador necessária.", 403)
    return user
