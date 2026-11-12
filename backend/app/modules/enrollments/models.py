from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.domain import utcnow
from app.models import Base
from app.modules.plans.models import Plan
from app.modules.students.models import Student


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        CheckConstraint("amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"),
        CheckConstraint("due_day BETWEEN 1 AND 31", name="due_day"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="date_order"),
        CheckConstraint("status IN ('ativa', 'cancelada')", name="status"),
        Index(
            "uq_enrollments_active_student_plan",
            "student_id",
            "plan_id",
            unique=True,
            sqlite_where=text("status = 'ativa'"),
            postgresql_where=text("status = 'ativa'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    due_day: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="ativa")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    student: Mapped[Student] = relationship()
    plan: Mapped[Plan] = relationship()


class EnrollmentSuspension(Base):
    __tablename__ = "enrollment_suspensions"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="time_order"),
        Index(
            "uq_suspensions_open_enrollment",
            "enrollment_id",
            unique=True,
            sqlite_where=text("ends_at IS NULL"),
            postgresql_where=text("ends_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    enrollment_id: Mapped[str] = mapped_column(ForeignKey("enrollments.id", ondelete="RESTRICT"))
    request_key: Mapped[str] = mapped_column(String(36), unique=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(String(500))
