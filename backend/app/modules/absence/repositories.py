from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.absence.models import AbsenceDetection, AbsenceScanState
from app.modules.attendance.models import CheckIn
from app.modules.enrollments.models import Enrollment, EnrollmentSuspension
from app.modules.students.models import Student

RULE_KEY = "absence-240h-v1"
OPEN_STATES = ("pendente", "em_acompanhamento")


class AbsenceRepository:
    def __init__(self, session: Session):
        self.session = session

    def open_for_student(self, student_id: str):
        return self.session.scalar(
            select(AbsenceDetection).where(
                AbsenceDetection.student_id == student_id,
                AbsenceDetection.status.in_(OPEN_STATES),
            )
        )

    def listing(self, status: str | None, offset: int, limit: int):
        query = select(AbsenceDetection, Student.name).join(Student)
        if status:
            query = query.where(AbsenceDetection.status == status)
        return self.session.execute(
            query.order_by(
                AbsenceDetection.detected_at.desc(),
                AbsenceDetection.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()

    def state(self):
        return self.session.scalar(
            select(AbsenceScanState)
            .where(AbsenceScanState.rule_key == RULE_KEY)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def students_after(self, cursor: str, limit: int):
        return self.session.scalars(
            select(Student.id).where(Student.id > cursor).order_by(Student.id).limit(limit)
        ).all()

    def enrollments(self, student_id: str):
        return self.session.scalars(
            select(Enrollment).where(Enrollment.student_id == student_id)
        ).all()

    def suspensions(self, student_id: str):
        return self.session.scalars(
            select(EnrollmentSuspension)
            .join(Enrollment)
            .where(Enrollment.student_id == student_id)
            .order_by(EnrollmentSuspension.starts_at, EnrollmentSuspension.id)
        ).all()

    def latest_visit(self, student_id: str):
        return self.session.scalar(
            select(CheckIn)
            .where(CheckIn.student_id == student_id)
            .order_by(CheckIn.occurred_at.desc(), CheckIn.id)
            .limit(1)
        )

    def existing(self, student_id: str, baseline):
        return self.session.scalar(
            select(AbsenceDetection).where(
                AbsenceDetection.student_id == student_id,
                AbsenceDetection.rule_key == RULE_KEY,
                AbsenceDetection.baseline_at == baseline,
            )
        )
