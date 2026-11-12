from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import Admin, BusinessSession
from app.core.domain import required
from app.modules.auth.dependencies import require_admin
from app.modules.students.repositories import StudentRepository
from app.modules.students.schemas import Deactivate, StudentCreate, StudentPublic
from app.modules.students.services import StudentService

router = APIRouter(
    prefix="/admin/students", tags=["Students"], dependencies=[Depends(require_admin)]
)


@router.post("", response_model=StudentPublic, status_code=201)
def create(data: StudentCreate, session: BusinessSession, actor: Admin):
    return StudentService(StudentRepository(session)).create(data, actor.id)


@router.get("", response_model=list[StudentPublic])
def listing(
    session: BusinessSession, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)
):
    return StudentRepository(session).list(offset, limit)


@router.get("/{student_id}", response_model=StudentPublic)
def detail(student_id: UUID, session: BusinessSession):
    return required(StudentRepository(session).get(str(student_id)), "Aluno")


@router.post("/{student_id}/deactivate", response_model=StudentPublic)
def deactivate(student_id: UUID, data: Deactivate, session: BusinessSession, actor: Admin):
    return StudentService(StudentRepository(session)).deactivate(str(student_id), data, actor.id)
