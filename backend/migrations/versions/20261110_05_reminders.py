"""Intenções duráveis e tentativas de lembretes simulados.

Revision ID: 20261110_05
Revises: 20261110_04
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_05"
down_revision = "20261110_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "monthly_fee_id",
            sa.String(36),
            sa.ForeignKey("monthly_fees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rule_key", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("cycle_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_cycles", sa.Integer(), nullable=False),
        sa.Column("publication_failures", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("suppression_reason", sa.String(40), nullable=True),
        sa.Column("receipt", sa.String(80), nullable=True, unique=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("monthly_fee_id", "rule_key", name="uq_reminders_fee_rule"),
        sa.CheckConstraint(
            "status IN ('pending', 'retry_wait', 'sent', 'exhausted', 'suppressed')", name="status"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND cycle_attempts BETWEEN 0 AND 3 "
            "AND retry_cycles BETWEEN 0 AND 3 AND publication_failures >= 0",
            name="counts",
        ),
        sa.CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL AND receipt IS NOT NULL) OR "
            "(status <> 'sent' AND sent_at IS NULL AND receipt IS NULL)",
            name="receipt",
        ),
    )
    op.create_index(
        "ix_reminders_pending", "reminders", ["status", "next_attempt_at", "lease_until"]
    )
    op.create_table(
        "reminder_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "reminder_id",
            sa.String(36),
            sa.ForeignKey("reminders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(12), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reminder_id", "number", name="uq_reminder_attempts_number"),
        sa.CheckConstraint("number > 0", name="number"),
        sa.CheckConstraint("outcome IN ('sent', 'failed')", name="outcome"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM reminders")):
        raise RuntimeError("Downgrade bloqueado: existem lembretes. Preserve o histórico.")
    op.drop_table("reminder_attempts")
    op.drop_table("reminders")
