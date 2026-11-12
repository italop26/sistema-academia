"""Presenças diárias e períodos de suspensão. Revision: 20261112_01."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_01"
down_revision = "20261110_05"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enrollments", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.execute(
        sa.text(
            "UPDATE enrollments SET cancelled_at = COALESCE("
            "(SELECT MAX(created_at) FROM audit_events WHERE entity_type = 'enrollment' "
            "AND entity_id = enrollments.id AND action = 'cancelled'), created_at) "
            "WHERE status = 'cancelada'"
        )
    )
    op.create_table(
        "enrollment_suspensions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "enrollment_id",
            sa.String(36),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(36), nullable=False, unique=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="time_order"),
    )
    op.create_index(
        "uq_suspensions_open_enrollment",
        "enrollment_suspensions",
        ["enrollment_id"],
        unique=True,
        sqlite_where=sa.text("ends_at IS NULL"),
        postgresql_where=sa.text("ends_at IS NULL"),
    )
    op.create_table(
        "check_ins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.String(36),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_day", sa.Date(), nullable=False),
        sa.UniqueConstraint("student_id", "local_day", name="uq_check_ins_student_day"),
    )
    op.create_index("ix_check_ins_student_time", "check_ins", ["student_id", "occurred_at"])
    op.create_table(
        "check_in_requests",
        sa.Column("idempotency_key", sa.String(36), primary_key=True),
        sa.Column(
            "check_in_id",
            sa.String(36),
            sa.ForeignKey("check_ins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "enrollment_id",
            sa.String(36),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM check_ins")) or connection.scalar(
        sa.text("SELECT count(*) FROM enrollment_suspensions")
    ):
        raise RuntimeError(
            "Downgrade bloqueado: existem presenças ou suspensões. Preserve o histórico."
        )
    op.drop_table("check_in_requests")
    op.drop_table("check_ins")
    op.drop_table("enrollment_suspensions")
    op.drop_column("enrollments", "cancelled_at")
