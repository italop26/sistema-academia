from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.domain import utcnow
from app.models import Base


class Reminder(Base):
    """Persistent intent and domain-specific outbox. Redis is only transport."""

    __tablename__ = "reminders"
    __table_args__ = (
        UniqueConstraint("monthly_fee_id", "rule_key", name="uq_reminders_fee_rule"),
        CheckConstraint(
            "status IN ('pending', 'retry_wait', 'sent', 'exhausted', 'suppressed')", name="status"
        ),
        CheckConstraint(
            "attempt_count >= 0 AND cycle_attempts BETWEEN 0 AND 3 "
            "AND retry_cycles BETWEEN 0 AND 3 AND publication_failures >= 0",
            name="counts",
        ),
        CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL AND receipt IS NOT NULL) OR "
            "(status <> 'sent' AND sent_at IS NULL AND receipt IS NULL)",
            name="receipt",
        ),
        Index("ix_reminders_pending", "status", "next_attempt_at", "lease_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    monthly_fee_id: Mapped[str] = mapped_column(ForeignKey("monthly_fees.id", ondelete="RESTRICT"))
    rule_key: Mapped[str] = mapped_column(String(40), default="overdue-v1")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    cycle_attempts: Mapped[int] = mapped_column(Integer, default=0)
    retry_cycles: Mapped[int] = mapped_column(Integer, default=0)
    publication_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    dispatch_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    suppression_reason: Mapped[str | None] = mapped_column(String(40))
    receipt: Mapped[str | None] = mapped_column(String(80), unique=True)
    message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReminderAttempt(Base):
    __tablename__ = "reminder_attempts"
    __table_args__ = (
        UniqueConstraint("reminder_id", "number", name="uq_reminder_attempts_number"),
        CheckConstraint("number > 0", name="number"),
        CheckConstraint("outcome IN ('sent', 'failed')", name="outcome"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    reminder_id: Mapped[str] = mapped_column(ForeignKey("reminders.id", ondelete="RESTRICT"))
    number: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(12))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
