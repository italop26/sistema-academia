"""Cobranças, pagamentos comuns e autoria automática no histórico.

Revision ID: 20261110_03
Revises: 20261110_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_03"
down_revision = "20261110_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "monthly_fee_id",
            sa.String(36),
            sa.ForeignKey("monthly_fees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("reference", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("expires_in_seconds", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint("provider", "reference", name="uq_charges_provider_reference"),
        sa.UniqueConstraint("provider", "idempotency_key", name="uq_charges_provider_idempotency"),
        sa.CheckConstraint(
            "amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"
        ),
        sa.CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        sa.CheckConstraint("currency = 'BRL'", name="currency"),
        sa.CheckConstraint("status IN ('pending', 'paid', 'cancelled')", name="status"),
        sa.CheckConstraint("expires_in_seconds BETWEEN 60 AND 86400", name="expiration_range"),
        sa.CheckConstraint("expires_at > created_at", name="expiration_order"),
        sa.CheckConstraint("provider <> 'simulated_pix' OR is_simulated = true", name="simulation"),
    )
    op.create_index("ix_charges_monthly_fee_id", "charges", ["monthly_fee_id"])
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "monthly_fee_id",
            sa.String(36),
            sa.ForeignKey("monthly_fees.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "charge_id",
            sa.String(36),
            sa.ForeignKey("charges.id", ondelete="RESTRICT"),
            nullable=True,
            unique=True,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(12), nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("external_payment_id", sa.String(128), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column(
            "actor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "external_payment_id", name="uq_payments_provider_external"
        ),
        sa.CheckConstraint(
            "amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"
        ),
        sa.CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        sa.CheckConstraint("currency = 'BRL'", name="currency"),
        sa.CheckConstraint("method IN ('manual', 'pix')", name="method"),
        sa.CheckConstraint(
            "(method = 'manual' AND actor_id IS NOT NULL AND charge_id IS NULL "
            "AND provider IS NULL AND external_payment_id IS NULL AND is_simulated = false) OR "
            "(method = 'pix' AND actor_id IS NULL AND charge_id IS NOT NULL "
            "AND provider IS NOT NULL AND external_payment_id IS NOT NULL)",
            name="origin",
        ),
        sa.CheckConstraint("provider <> 'simulated_pix' OR is_simulated = true", name="simulation"),
    )
    # IDs, amounts, authors, notes and timestamps survive unchanged. No second ledger is kept.
    op.execute(
        sa.text(
            "INSERT INTO payments (id, monthly_fee_id, amount_cents, actor_id, note, paid_at, "
            "method, currency, is_simulated) "
            "SELECT id, monthly_fee_id, amount_cents, actor_id, note, paid_at, "
            "'manual', 'BRL', false "
            "FROM manual_payments"
        )
    )
    op.drop_table("manual_payments")
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(
            sa.Column("actor_type", sa.String(12), server_default="admin", nullable=False)
        )
        batch.alter_column("actor_id", existing_type=sa.String(36), nullable=True)
        batch.create_check_constraint(
            "actor_origin",
            "(actor_type = 'admin' AND actor_id IS NOT NULL) OR "
            "(actor_type = 'system' AND actor_id IS NULL)",
        )


def downgrade() -> None:
    connection = op.get_bind()
    # Never silently discard the new financial history on a backward migration.
    if (
        connection.scalar(sa.text("SELECT count(*) FROM charges"))
        or connection.scalar(sa.text("SELECT count(*) FROM payments WHERE method <> 'manual'"))
        or connection.scalar(
            sa.text("SELECT count(*) FROM audit_events WHERE actor_type = 'system'")
        )
    ):
        raise RuntimeError(
            "Downgrade bloqueado: existem cobranças ou registros automáticos. "
            "Preserve os dados e planeje uma migração específica."
        )
    op.create_table(
        "manual_payments",
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
        sa.CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
    )
    op.execute(
        sa.text(
            "INSERT INTO manual_payments "
            "(id, monthly_fee_id, amount_cents, actor_id, note, paid_at) "
            "SELECT id, monthly_fee_id, amount_cents, actor_id, note, paid_at FROM payments"
        )
    )
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint(op.f("ck_audit_events_actor_origin"), type_="check")
        batch.alter_column("actor_id", existing_type=sa.String(36), nullable=False)
        batch.drop_column("actor_type")
    op.drop_table("payments")
    op.drop_table("charges")
