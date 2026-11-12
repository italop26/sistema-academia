"""Alunos, planos, matrículas e histórico administrativo.

Revision ID: 20261110_01
Revises: 20261109_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_01"
down_revision = "20261109_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            unique=True,
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "plans",
        sa.CheckConstraint(
            "monthly_amount_cents = CAST(monthly_amount_cents AS INTEGER)", name="integer_amount"
        ),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("monthly_amount_cents", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "monthly_amount_cents > 0 AND monthly_amount_cents <= 2000000000",
            name="positive_amount",
        ),
    )
    op.create_table(
        "enrollments",
        sa.CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plan_id", sa.String(36), sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("due_day", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"
        ),
        sa.CheckConstraint("due_day BETWEEN 1 AND 31", name="due_day"),
        sa.CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="date_order"),
        sa.CheckConstraint("status IN ('ativa', 'cancelada')", name="status"),
    )
    op.create_index(
        "uq_enrollments_active_student_plan",
        "enrollments",
        ["student_id", "plan_id"],
        unique=True,
        sqlite_where=sa.text("status = 'ativa'"),
        postgresql_where=sa.text("status = 'ativa'"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("before", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_entity", "audit_events", ["entity_type", "entity_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("enrollments")
    op.drop_table("plans")
    op.drop_table("students")
