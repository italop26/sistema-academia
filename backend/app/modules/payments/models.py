from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.domain import utcnow
from app.models import Base


class Charge(Base):
    __tablename__ = "charges"
    __table_args__ = (
        UniqueConstraint("provider", "reference", name="uq_charges_provider_reference"),
        UniqueConstraint("provider", "idempotency_key", name="uq_charges_provider_idempotency"),
        CheckConstraint("amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"),
        CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        CheckConstraint("currency = 'BRL'", name="currency"),
        CheckConstraint("status IN ('pending', 'paid', 'cancelled')", name="status"),
        CheckConstraint("expires_in_seconds BETWEEN 60 AND 86400", name="expiration_range"),
        CheckConstraint("expires_at > created_at", name="expiration_order"),
        CheckConstraint("provider <> 'simulated_pix' OR is_simulated = true", name="simulation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    monthly_fee_id: Mapped[str] = mapped_column(
        ForeignKey("monthly_fees.id", ondelete="RESTRICT"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    status: Mapped[str] = mapped_column(String(12), default="pending")
    is_simulated: Mapped[bool] = mapped_column(Boolean)
    expires_in_seconds: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "external_payment_id", name="uq_payments_provider_external"),
        CheckConstraint("amount_cents > 0 AND amount_cents <= 2000000000", name="positive_amount"),
        CheckConstraint("amount_cents = CAST(amount_cents AS INTEGER)", name="integer_amount"),
        CheckConstraint("currency = 'BRL'", name="currency"),
        CheckConstraint("method IN ('manual', 'pix')", name="method"),
        CheckConstraint(
            "(method = 'manual' AND actor_id IS NOT NULL AND charge_id IS NULL "
            "AND provider IS NULL AND external_payment_id IS NULL AND is_simulated = false) OR "
            "(method = 'pix' AND actor_id IS NULL AND charge_id IS NOT NULL "
            "AND provider IS NOT NULL AND external_payment_id IS NOT NULL)",
            name="origin",
        ),
        CheckConstraint("provider <> 'simulated_pix' OR is_simulated = true", name="simulation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    monthly_fee_id: Mapped[str] = mapped_column(
        ForeignKey("monthly_fees.id", ondelete="RESTRICT"),
        unique=True,
    )
    charge_id: Mapped[str | None] = mapped_column(
        ForeignKey("charges.id", ondelete="RESTRICT"),
        unique=True,
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    method: Mapped[str] = mapped_column(String(12), default="manual")
    provider: Mapped[str | None] = mapped_column(String(64))
    external_payment_id: Mapped[str | None] = mapped_column(String(128))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    note: Mapped[str] = mapped_column(String(500))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
