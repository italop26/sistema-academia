from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.modules.auth.dependencies import CurrentUser, bearer, get_auth_service, require_admin
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.services import AuthService
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return service.login(data)


@router.get("/me", response_model=UserPublic)
def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


@router.get("/admin", response_model=UserPublic)
def admin(user: Annotated[User, Depends(require_admin)]) -> UserPublic:
    return UserPublic.model_validate(user)


@router.post("/logout", status_code=204)
def logout(
    user: CurrentUser,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    service.logout(credentials.credentials)
    return Response(status_code=204)
