from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import Admin, BusinessSession
from app.core.domain import ReasonRequest
from app.modules.auth.dependencies import require_admin
from app.modules.plans.repositories import PlanRepository
from app.modules.plans.schemas import PlanCreate, PlanPublic
from app.modules.plans.services import PlanService

router = APIRouter(prefix="/admin/plans", tags=["Plans"], dependencies=[Depends(require_admin)])


@router.post("", response_model=PlanPublic, status_code=201)
def create(data: PlanCreate, session: BusinessSession, actor: Admin):
    return PlanService(PlanRepository(session)).create(data, actor.id)


@router.get("", response_model=list[PlanPublic])
def listing(
    session: BusinessSession, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)
):
    return PlanRepository(session).list(offset, limit)


@router.post("/{plan_id}/deactivate", response_model=PlanPublic)
def deactivate(plan_id: UUID, data: ReasonRequest, session: BusinessSession, actor: Admin):
    return PlanService(PlanRepository(session)).deactivate(str(plan_id), data, actor.id)
