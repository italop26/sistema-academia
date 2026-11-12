from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class AbsenceScanState(Base):
    """Durable activation, cursor and lease; Celery results are never business state."""

    __tablename__ = "absence_scan_state"
    __table_args__ = (CheckConstraint("consecutive_failures >= 0", name="failures"),)

    rule_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str] = mapped_column(String(36), default="")
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AbsenceDetection(Base):
    """One historical absence episode and its small administrative workflow."""

    __tablename__ = "absence_detections"
    __table_args__ = (
        UniqueConstraint("student_id", "rule_key", "baseline_at", name="uq_absence_episode"),
        CheckConstraint("detected_at >= baseline_at", name="date_order"),
        CheckConstraint(
            "status IN ('pendente', 'em_acompanhamento', 'resolvido', 'encerrado')", name="status"
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "(status IN ('pendente', 'em_acompanhamento') AND closed_at IS NULL) OR "
            "(status IN ('resolvido', 'encerrado') AND closed_at IS NOT NULL)",
            name="closure",
        ),
        Index(
            "uq_absence_open_student",
            "student_id",
            unique=True,
            sqlite_where=text("status IN ('pendente', 'em_acompanhamento')"),
            postgresql_where=text("status IN ('pendente', 'em_acompanhamento')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), index=True
    )
    rule_key: Mapped[str] = mapped_column(String(40))
    baseline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_check_in_id: Mapped[str | None] = mapped_column(
        ForeignKey("check_ins.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(20), default="pendente", server_default="pendente")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    last_note: Mapped[str | None] = mapped_column(String(500))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class AbsenceScanRun(Base):
    __tablename__ = "absence_scan_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'interrupted')", name="status"
        ),
        CheckConstraint("processed >= 0 AND detected >= 0", name="counts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    processed: Mapped[int] = mapped_column(Integer, default=0)
    detected: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
