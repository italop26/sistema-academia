from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.payments.models import Charge, Payment


class PaymentRepository:
    def __init__(self, session: Session):
        self.session = session

    def charge(self, charge_id: str, lock: bool = False):
        query = select(Charge).where(Charge.id == charge_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def by_key(self, provider: str, key: str):
        return self.session.scalar(
            select(Charge).where(
                Charge.provider == provider,
                Charge.idempotency_key == key,
            )
        )

    def charges(self, fee_id: str, offset: int = 0, limit: int = 100):
        return self.session.scalars(
            select(Charge)
            .where(Charge.monthly_fee_id == fee_id)
            .order_by(
                Charge.created_at,
                Charge.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()

    def pending_charges(self, fee_id: str):
        return self.session.scalars(
            select(Charge)
            .where(
                Charge.monthly_fee_id == fee_id,
                Charge.status == "pending",
            )
            .order_by(Charge.id)
            .with_for_update()
        ).all()

    def payment(self, fee_id: str):
        return self.session.scalar(select(Payment).where(Payment.monthly_fee_id == fee_id))

    def by_external_id(self, provider: str, external_id: str):
        return self.session.scalar(
            select(Payment).where(
                Payment.provider == provider,
                Payment.external_payment_id == external_id,
            )
        )

    def add(self, item):
        self.session.add(item)
        self.session.flush()
