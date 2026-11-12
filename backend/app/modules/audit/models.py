from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.domain import utcnow
from app.models import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),
        CheckConstraint(
            "(actor_type = 'admin' AND actor_id IS NOT NULL) OR "
            "(actor_type = 'system' AND actor_id IS NULL)",
            name="actor_origin",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_type: Mapped[str] = mapped_column(
        String(12), default="admin", server_default=text("'admin'")
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    before: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
