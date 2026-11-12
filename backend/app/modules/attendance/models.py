from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.domain import utcnow
from app.models import Base


class CheckIn(Base):
    __tablename__ = "check_ins"
    __table_args__ = (
        UniqueConstraint("student_id", "local_day", name="uq_check_ins_student_day"),
        Index("ix_check_ins_student_time", "student_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id", ondelete="RESTRICT"))
    enrollment_id: Mapped[str] = mapped_column(ForeignKey("enrollments.id", ondelete="RESTRICT"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    local_day: Mapped[date] = mapped_column(Date)


class CheckInRequest(Base):
    """Every accepted key remains bound to its original request, including daily duplicates."""

    __tablename__ = "check_in_requests"

    idempotency_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    check_in_id: Mapped[str] = mapped_column(ForeignKey("check_ins.id", ondelete="RESTRICT"))
    enrollment_id: Mapped[str] = mapped_column(ForeignKey("enrollments.id", ondelete="RESTRICT"))
