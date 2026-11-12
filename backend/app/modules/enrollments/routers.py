from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import Admin, BusinessSession
from app.core.domain import ReasonRequest, required
from app.modules.auth.dependencies import require_admin
from app.modules.enrollments.repositories import EnrollmentRepository
from app.modules.enrollments.schemas import (
    EnrollmentCreate,
    EnrollmentPublic,
    SuspensionCreate,
    SuspensionPublic,
)
from app.modules.enrollments.services import EnrollmentService

router = APIRouter(
    prefix="/admin/enrollments", tags=["Enrollments"], dependencies=[Depends(require_admin)]
)


@router.post("", response_model=EnrollmentPublic, status_code=201)
def create(data: EnrollmentCreate, session: BusinessSession, actor: Admin):
    return EnrollmentService(EnrollmentRepository(session)).create(data, actor.id)


@router.get("", response_model=list[EnrollmentPublic])
def listing(
    session: BusinessSession,
    student_id: UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    return EnrollmentRepository(session).list(
        str(student_id) if student_id else None, offset, limit
    )


@router.get("/{enrollment_id}", response_model=EnrollmentPublic)
def detail(enrollment_id: UUID, session: BusinessSession):
    return required(EnrollmentRepository(session).get(str(enrollment_id)), "Matrícula")


@router.post("/{enrollment_id}/cancel", response_model=EnrollmentPublic)
def cancel(enrollment_id: UUID, data: ReasonRequest, session: BusinessSession, actor: Admin):
    return EnrollmentService(EnrollmentRepository(session)).cancel(
        str(enrollment_id), data, actor.id
    )


@router.post("/{enrollment_id}/suspend", response_model=SuspensionPublic)
def suspend(enrollment_id: UUID, data: SuspensionCreate, session: BusinessSession, actor: Admin):
    return EnrollmentService(EnrollmentRepository(session)).suspend(
        str(enrollment_id), data, actor.id
    )


@router.get("/{enrollment_id}/suspensions", response_model=list[SuspensionPublic])
def suspensions(
    enrollment_id: UUID,
    session: BusinessSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    required(EnrollmentRepository(session).get(str(enrollment_id)), "Matrícula")
    return EnrollmentRepository(session).suspensions(str(enrollment_id), offset, limit)


@router.post("/{enrollment_id}/suspensions/{suspension_id}/resume", response_model=SuspensionPublic)
def resume(
    enrollment_id: UUID,
    suspension_id: UUID,
    data: ReasonRequest,
    session: BusinessSession,
    actor: Admin,
):
    return EnrollmentService(EnrollmentRepository(session)).resume(
        str(enrollment_id), str(suspension_id), data, actor.id
    )
