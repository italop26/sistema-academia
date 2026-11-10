from typing import Annotated

from fastapi import APIRouter, Depends, Response
from redis import Redis
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.redis import get_redis
from app.modules.health.repositories import HealthRepository
from app.modules.health.schemas import HealthResponse
from app.modules.health.services import HealthService

router = APIRouter(prefix="/health", tags=["Infrastructure"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def health(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> HealthResponse:
    result = HealthService(HealthRepository(session), redis).check()
    if result.status != "ok":
        response.status_code = 503
    return result
