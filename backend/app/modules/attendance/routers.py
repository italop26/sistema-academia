from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import Admin, BusinessSession
from app.core.domain import required
from app.modules.attendance.repositories import AttendanceRepository
from app.modules.attendance.schemas import AttendanceSummary, CheckInCreate, CheckInPublic
from app.modules.attendance.services import AttendanceService
from app.modules.auth.dependencies import require_admin
from app.modules.students.repositories import StudentRepository

router = APIRouter(
    prefix="/admin/attendance", tags=["Attendance"], dependencies=[Depends(require_admin)]
)


@router.post("/check-ins", response_model=CheckInPublic)
def check_in(data: CheckInCreate, session: BusinessSession, actor: Admin):
    return AttendanceService(AttendanceRepository(session)).check_in(data, actor.id)


@router.get("/students/{student_id}", response_model=AttendanceSummary)
def summary(student_id: UUID, session: BusinessSession):
    required(StudentRepository(session).get(str(student_id)), "Aluno")
    return AttendanceRepository(session).summary(str(student_id))


@router.get("/students/{student_id}/check-ins", response_model=list[CheckInPublic])
def history(
    student_id: UUID,
    session: BusinessSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
):
    required(StudentRepository(session).get(str(student_id)), "Aluno")
    return AttendanceRepository(session).list(str(student_id), offset, limit)
