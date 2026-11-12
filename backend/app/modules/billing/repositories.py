from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.modules.billing.models import MonthlyFee
from app.modules.enrollments.models import Enrollment
from app.modules.payments.repositories import PaymentRepository


class BillingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, fee_id: str, lock: bool = False):
        query = select(MonthlyFee).where(MonthlyFee.id == fee_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def by_competence(self, enrollment_id: str, competence: date):
        return self.session.scalar(
            select(MonthlyFee).where(
                MonthlyFee.enrollment_id == enrollment_id,
                MonthlyFee.competence == competence,
            )
        )

    def list(self, student_id: str | None, competence: date | None, offset: int, limit: int):
        query = (
            select(MonthlyFee)
            .join(Enrollment)
            .options(
                joinedload(MonthlyFee.enrollment).joinedload(Enrollment.student),
                joinedload(MonthlyFee.payment),
            )
        )
        if student_id:
            query = query.where(Enrollment.student_id == student_id)
        if competence:
            query = query.where(MonthlyFee.competence == competence)
        return self.session.scalars(
            query.order_by(MonthlyFee.competence.desc(), MonthlyFee.id).offset(offset).limit(limit)
        ).all()

    def payment(self, fee_id: str):
        return PaymentRepository(self.session).payment(fee_id)

    def add(self, item):
        self.session.add(item)
        self.session.flush()
