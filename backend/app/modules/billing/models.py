from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    column,
    extract,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.domain import utcnow
from app.models import Base
from app.modules.enrollments.models import Enrollment
from app.modules.payments.models import Payment


class MonthlyFee(Base):
    __tablename__ = "monthly_fees"
    __table_args__ = (
        CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        UniqueConstraint(
            "enrollment_id", "competence", name="uq_monthly_fees_enrollment_competence"
        ),
        CheckConstraint("amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"),
        CheckConstraint("status IN ('pendente', 'paga', 'cancelada')", name="status"),
        CheckConstraint(
            "(status = 'paga' AND paid_at IS NOT NULL) OR (status <> 'paga' AND paid_at IS NULL)",
            name="paid_timestamp",
        ),
        CheckConstraint(extract("day", column("competence")) == 1, name="competence_first_day"),
        Index("ix_monthly_fees_status_due", "status", "due_on"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    enrollment_id: Mapped[str] = mapped_column(ForeignKey("enrollments.id", ondelete="RESTRICT"))
    competence: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="pendente")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    enrollment: Mapped[Enrollment] = relationship()
    payment: Mapped[Payment | None] = relationship()


# Compatibility import for existing callers; only one payment table/mapper exists.
ManualPayment = Payment
