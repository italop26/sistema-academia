from zoneinfo import ZoneInfo

from app.core.database import write_transaction
from app.core.domain import required, utcnow
from app.core.errors import ApplicationError
from app.modules.absence.followups import resolve_on_check_in
from app.modules.attendance.models import CheckIn, CheckInRequest
from app.modules.attendance.repositories import AttendanceRepository
from app.modules.attendance.schemas import CheckInCreate, CheckInPublic
from app.modules.audit.repositories import record_event
from app.modules.enrollments.repositories import EnrollmentRepository
from app.modules.students.repositories import StudentRepository


class AttendanceService:
    def __init__(self, repository: AttendanceRepository):
        self.repository = repository

    def check_in(self, data: CheckInCreate, actor_id: str):
        session = self.repository.session
        student_id, enrollment_id = str(data.student_id), str(data.enrollment_id)
        key = str(data.idempotency_key)
        with write_transaction(session):
            student = required(StudentRepository(session).get(student_id, lock=True), "Aluno")
            previous = self.repository.request(key)
            if previous:
                visit = session.get(CheckIn, previous.check_in_id)
                if previous.enrollment_id != enrollment_id or visit.student_id != student_id:
                    raise ApplicationError(
                        "idempotency_conflict", "Chave já utilizada em outra operação.", 409
                    )
                return CheckInPublic.model_validate(visit)
            enrollment = required(
                EnrollmentRepository(session).get(enrollment_id, lock=True), "Matrícula"
            )
            now = utcnow()
            day = now.astimezone(ZoneInfo("America/Fortaleza")).date()
            if (
                enrollment.student_id != student_id
                or not student.is_active
                or enrollment.status != "ativa"
                or enrollment.starts_on > day
                or (enrollment.ends_on is not None and enrollment.ends_on < day)
                or EnrollmentRepository(session).open_suspension(enrollment_id)
            ):
                raise ApplicationError(
                    "attendance_ineligible", "Aluno sem matrícula disponível para presença.", 409
                )
            visit = self.repository.on_day(student_id, day)
            if visit is None:
                visit = CheckIn(
                    student_id=student_id,
                    enrollment_id=enrollment_id,
                    actor_id=actor_id,
                    occurred_at=now,
                    local_day=day,
                )
                session.add(visit)
                session.flush()
                record_event(
                    session,
                    "check_in",
                    visit.id,
                    "recorded",
                    actor_id,
                    CheckInPublic.model_validate(visit).model_dump(mode="json"),
                )
            resolve_on_check_in(session, visit, actor_id)
            session.add(
                CheckInRequest(
                    idempotency_key=key, check_in_id=visit.id, enrollment_id=enrollment_id
                )
            )
            result = CheckInPublic.model_validate(visit)
        return result
