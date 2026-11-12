"""Caixa de entrada durável para webhooks Pix simulados.

Revision ID: 20261110_04
Revises: 20261110_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_04"
down_revision = "20261110_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_event_id", sa.String(36), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("delivery_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("last_conflict_hash", sa.String(64), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("result_code", sa.String(64), nullable=True),
        sa.Column(
            "charge_id",
            sa.String(36),
            sa.ForeignKey("charges.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "payment_id",
            sa.String(36),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "provider", "external_event_id", name="uq_webhook_events_provider_event"
        ),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'ignored', 'rejected', 'failed')", name="status"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND delivery_count >= 1 AND conflict_count >= 0", name="counts"
        ),
    )
    op.create_index(
        "ix_webhook_events_status_received", "webhook_events", ["status", "received_at"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM webhook_events")):
        raise RuntimeError("Downgrade bloqueado: existem eventos de webhook. Preserve o histórico.")
    op.drop_table("webhook_events")
