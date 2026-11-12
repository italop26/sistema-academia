from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.enrollments.models import Enrollment, EnrollmentSuspension


class EnrollmentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, enrollment_id: str, lock: bool = False):
        query = select(Enrollment).where(Enrollment.id == enrollment_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def list(self, student_id: str | None, offset: int, limit: int):
        query = select(Enrollment)
        if student_id:
            query = query.where(Enrollment.student_id == student_id)
        return self.session.scalars(
            query.order_by(Enrollment.created_at, Enrollment.id).offset(offset).limit(limit)
        ).all()

    def add(self, enrollment: Enrollment):
        self.session.add(enrollment)
        self.session.flush()

    def open_suspension(self, enrollment_id: str):
        return self.session.scalar(
            select(EnrollmentSuspension).where(
                EnrollmentSuspension.enrollment_id == enrollment_id,
                EnrollmentSuspension.ends_at.is_(None),
            )
        )

    def suspensions(self, enrollment_id: str, offset: int, limit: int):
        return self.session.scalars(
            select(EnrollmentSuspension)
            .where(
                EnrollmentSuspension.enrollment_id == enrollment_id,
            )
            .order_by(EnrollmentSuspension.starts_at.desc(), EnrollmentSuspension.id)
            .offset(offset)
            .limit(limit)
        ).all()
