"""Detecção de ausência e progresso durável. Revision: 20261112_02."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_02"
down_revision = "20261112_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "absence_scan_state",
        sa.Column("rule_key", sa.String(40), primary_key=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cursor", sa.String(36), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("consecutive_failures >= 0", name="failures"),
    )
    op.create_table(
        "absence_detections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rule_key", sa.String(40), nullable=False),
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_check_in_id", sa.String(36), sa.ForeignKey("check_ins.id", ondelete="RESTRICT")
        ),
        sa.UniqueConstraint("student_id", "rule_key", "baseline_at", name="uq_absence_episode"),
        sa.CheckConstraint("detected_at >= baseline_at", name="date_order"),
    )
    op.create_index("ix_absence_detections_student_id", "absence_detections", ["student_id"])
    op.create_table(
        "absence_scan_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("detected", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'interrupted')", name="status"
        ),
        sa.CheckConstraint("processed >= 0 AND detected >= 0", name="counts"),
    )


def downgrade():
    connection = op.get_bind()
    if any(
        connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        for table in (
            "absence_detections",
            "absence_scan_state",
            "absence_scan_runs",
        )
    ):
        raise RuntimeError("Downgrade bloqueado: existe histórico de ausência. Preserve os dados.")
    op.drop_table("absence_scan_runs")
    op.drop_table("absence_detections")
    op.drop_table("absence_scan_state")
