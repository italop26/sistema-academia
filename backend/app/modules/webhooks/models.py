from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.domain import utcnow
from app.models import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id", name="uq_webhook_events_provider_event"),
        CheckConstraint(
            "status IN ('received', 'processed', 'ignored', 'rejected', 'failed')", name="status"
        ),
        CheckConstraint(
            "attempt_count >= 0 AND delivery_count >= 1 AND conflict_count >= 0", name="counts"
        ),
        Index("ix_webhook_events_status_received", "status", "received_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(64))
    external_event_id: Mapped[str] = mapped_column(String(36))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default="received")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    delivery_count: Mapped[int] = mapped_column(Integer, default=1)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    last_conflict_hash: Mapped[str | None] = mapped_column(String(64))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    result_code: Mapped[str | None] = mapped_column(String(64))
    charge_id: Mapped[str | None] = mapped_column(ForeignKey("charges.id", ondelete="RESTRICT"))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
