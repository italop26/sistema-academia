from datetime import date, datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.billing.models import MonthlyFee
from app.modules.enrollments.models import Enrollment
from app.modules.notifications.models import Reminder, ReminderAttempt
from app.modules.payments.models import Payment
from app.modules.students.models import Student

RULE_KEY = "overdue-v1"
ACTIVE_STATES = ("pending", "retry_wait")


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, reminder_id: str, lock: bool = False):
        query = select(Reminder).where(Reminder.id == reminder_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def for_fee(self, fee_id: str):
        return self.session.scalar(
            select(Reminder).where(
                Reminder.monthly_fee_id == fee_id,
                Reminder.rule_key == RULE_KEY,
            )
        )

    def overdue_ids(self, today: date, limit: int):
        return self.session.scalars(
            select(MonthlyFee.id)
            .where(
                MonthlyFee.status == "pendente",
                MonthlyFee.due_on < today,
                ~exists(
                    select(Reminder.id).where(
                        Reminder.monthly_fee_id == MonthlyFee.id, Reminder.rule_key == RULE_KEY
                    )
                ),
                ~exists(select(Payment.id).where(Payment.monthly_fee_id == MonthlyFee.id)),
            )
            .order_by(MonthlyFee.due_on, MonthlyFee.id)
            .limit(limit)
        ).all()

    def due_ids(self, now: datetime, limit: int):
        return self.session.scalars(
            select(Reminder.id)
            .where(
                Reminder.status.in_(ACTIVE_STATES),
                Reminder.next_attempt_at <= now,
                or_(Reminder.lease_until.is_(None), Reminder.lease_until <= now),
            )
            .order_by(Reminder.next_attempt_at, Reminder.id)
            .limit(limit)
        ).all()

    def list(self, student_id: str | None, status: str | None, offset: int, limit: int):
        query = (
            select(
                Reminder,
                Student.name,
                Student.id,
                MonthlyFee.competence,
                MonthlyFee.due_on,
                MonthlyFee.amount_cents,
            )
            .join(
                MonthlyFee,
                Reminder.monthly_fee_id == MonthlyFee.id,
            )
            .join(Enrollment, MonthlyFee.enrollment_id == Enrollment.id)
            .join(Student)
        )
        if student_id:
            query = query.where(Student.id == student_id)
        if status:
            query = query.where(Reminder.status == status)
        return self.session.execute(
            query.order_by(
                Reminder.created_at.desc(),
                Reminder.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()

    def attempts(self, reminder_id: str):
        return self.session.scalars(
            select(ReminderAttempt)
            .where(
                ReminderAttempt.reminder_id == reminder_id,
            )
            .order_by(ReminderAttempt.number)
        ).all()

    def summary(self):
        return dict(
            self.session.execute(
                select(Reminder.status, func.count()).group_by(
                    Reminder.status,
                )
            ).all()
        )
