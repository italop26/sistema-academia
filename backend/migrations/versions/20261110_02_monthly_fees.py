"""Mensalidades por competência e baixas manuais.

Revision ID: 20261110_02
Revises: 20261110_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_02"
down_revision = "20261110_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_fees",
        sa.CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "enrollment_id",
            sa.String(36),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("competence", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "enrollment_id", "competence", name="uq_monthly_fees_enrollment_competence"
        ),
        sa.CheckConstraint(
            "amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"
        ),
        sa.CheckConstraint("status IN ('pendente', 'paga', 'cancelada')", name="status"),
        sa.CheckConstraint(
            "(status = 'paga' AND paid_at IS NOT NULL) OR (status <> 'paga' AND paid_at IS NULL)",
            name="paid_timestamp",
        ),
        sa.CheckConstraint(
            sa.extract("day", sa.column("competence")) == 1, name="competence_first_day"
        ),
    )
    op.create_index("ix_monthly_fees_status_due", "monthly_fees", ["status", "due_on"])
    op.create_table(
        "manual_payments",
        sa.CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "monthly_fee_id",
            sa.String(36),
            sa.ForeignKey("monthly_fees.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"
        ),
    )


def downgrade() -> None:
    op.drop_table("manual_payments")
    op.drop_table("monthly_fees")
