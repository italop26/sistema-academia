from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.database import write_transaction
from app.core.domain import required, utcnow
from app.core.errors import ApplicationError
from app.modules.audit.repositories import record_event
from app.modules.billing.models import MonthlyFee
from app.modules.billing.presenters import fee_public
from app.modules.billing.repositories import BillingRepository
from app.modules.payments.models import Charge, Payment
from app.modules.payments.providers import SIMULATION_NOTICE, ChargeRequest, get_pix_provider
from app.modules.payments.repositories import PaymentRepository
from app.modules.payments.schemas import ChargeCreate, ChargePublic, SimulatedReceipt


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def charge_public(charge: Charge) -> ChargePublic:
    status = charge.status
    if status == "pending" and as_utc(charge.expires_at) <= utcnow():
        status = "expired"
    return ChargePublic(
        id=charge.id,
        monthly_fee_id=charge.monthly_fee_id,
        provider=charge.provider,
        reference=charge.reference,
        idempotency_key=charge.idempotency_key,
        amount_cents=charge.amount_cents,
        currency=charge.currency,
        status=status,
        is_simulated=charge.is_simulated,
        simulation_notice=SIMULATION_NOTICE if charge.is_simulated else None,
        expires_at=charge.expires_at,
        created_at=charge.created_at,
        created_by=charge.created_by,
    )


class ChargeService:
    def __init__(self, repository: PaymentRepository):
        self.repository = repository

    def create(self, data: ChargeCreate, actor_id: str) -> ChargePublic:
        provider = get_pix_provider()
        session = self.repository.session
        with write_transaction(session):
            fee = required(
                BillingRepository(session).get(str(data.monthly_fee_id), lock=True), "Mensalidade"
            )
            existing = self.repository.by_key(provider.name, str(data.idempotency_key))
            if existing:
                if (
                    existing.monthly_fee_id != fee.id
                    or existing.expires_in_seconds != data.expires_in_seconds
                ):
                    raise ApplicationError(
                        "idempotency_conflict", "Chave usada para outra solicitação.", 409
                    )
                return charge_public(existing)
            if fee.status != "pendente":
                raise ApplicationError(
                    "invalid_transition", "Mensalidade não permite nova cobrança.", 409
                )
            timestamp = utcnow()
            charge_id = str(uuid4())
            # Only the local adapter runs here, without network I/O.
            result = provider.create_charge(
                ChargeRequest(
                    charge_id=charge_id,
                    monthly_fee_id=fee.id,
                    amount_cents=fee.amount_cents,
                    currency="BRL",
                    expires_at=timestamp + timedelta(seconds=data.expires_in_seconds),
                )
            )
            charge = Charge(
                id=charge_id,
                monthly_fee_id=fee.id,
                provider=provider.name,
                reference=result.reference,
                idempotency_key=str(data.idempotency_key),
                amount_cents=fee.amount_cents,
                currency="BRL",
                is_simulated=provider.is_simulated,
                expires_in_seconds=data.expires_in_seconds,
                expires_at=result.expires_at,
                created_at=timestamp,
                created_by=actor_id,
            )
            self.repository.add(charge)
            output = charge_public(charge)
            record_event(
                session, "charge", charge.id, "created", actor_id, output.model_dump(mode="json")
            )
        return output


class SettlementService:
    """Common rules; settle_locked requires an owned write transaction and a locked fee."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = PaymentRepository(session)

    def cancel_pending_charges(
        self, fee_id: str, actor_id: str | None, reason: str, except_id: str | None = None
    ):
        for charge in self.repository.pending_charges(fee_id):
            if charge.id == except_id:
                continue
            before = charge_public(charge).model_dump(mode="json")
            charge.status = "cancelled"
            record_event(
                self.session,
                "charge",
                charge.id,
                "cancelled",
                actor_id,
                charge_public(charge).model_dump(mode="json"),
                before,
                reason,
            )

    def settle_locked(
        self,
        fee: MonthlyFee,
        *,
        amount_cents: int,
        currency: str,
        actor_id: str | None,
        note: str,
        charge: Charge | None = None,
        external_payment_id: str | None = None,
    ) -> Payment:
        if not self.session.in_transaction():
            raise RuntimeError("Settlement requires an explicit write transaction")
        if amount_cents != fee.amount_cents or currency != "BRL":
            raise ApplicationError(
                "amount_mismatch", "Valor ou moeda divergente da mensalidade.", 409
            )
        if fee.status == "cancelada":
            raise ApplicationError(
                "invalid_transition", "Mensalidade cancelada não pode ser paga.", 409
            )
        if charge is None and actor_id is None:
            raise ApplicationError("invalid_origin", "Baixa manual exige responsável.", 409)
        if charge:
            provider = get_pix_provider()
            if (
                charge.monthly_fee_id != fee.id
                or charge.provider != provider.name
                or not charge.is_simulated
                or charge.amount_cents != amount_cents
                or charge.currency != currency
                or not external_payment_id
                or actor_id is not None
            ):
                raise ApplicationError("invalid_charge", "Cobrança ou origem incompatível.", 409)
            used = self.repository.by_external_id(charge.provider, external_payment_id)
            if used and (used.monthly_fee_id != fee.id or used.charge_id != charge.id):
                raise ApplicationError(
                    "payment_conflict", "Referência de pagamento já utilizada.", 409
                )
        existing = self.repository.payment(fee.id)
        if existing:
            same_origin = (charge is None and existing.method == "manual") or (
                charge is not None
                and existing.charge_id == charge.id
                and existing.external_payment_id == external_payment_id
            )
            if fee.status == "paga" and same_origin:
                return existing
            raise ApplicationError("payment_conflict", "Mensalidade já possui recebimento.", 409)
        if fee.status != "pendente":
            raise ApplicationError("invalid_transition", "Estado financeiro inconsistente.", 409)
        if charge and (charge.status != "pending" or as_utc(charge.expires_at) <= utcnow()):
            raise ApplicationError("invalid_charge", "Cobrança encerrada ou expirada.", 409)
        before = fee_public(fee).model_dump(mode="json")
        timestamp = utcnow()
        payment = Payment(
            monthly_fee_id=fee.id,
            charge_id=charge.id if charge else None,
            amount_cents=amount_cents,
            currency=currency,
            method="pix" if charge else "manual",
            provider=charge.provider if charge else None,
            external_payment_id=external_payment_id if charge else None,
            is_simulated=charge.is_simulated if charge else False,
            actor_id=actor_id,
            note=note,
            paid_at=timestamp,
        )
        fee.status, fee.paid_at = "paga", timestamp
        self.repository.add(payment)
        fee.payment = payment
        if charge:
            previous = charge_public(charge).model_dump(mode="json")
            charge.status = "paid"
            record_event(
                self.session,
                "charge",
                charge.id,
                "paid",
                None,
                charge_public(charge).model_dump(mode="json"),
                previous,
                SIMULATION_NOTICE,
            )
        self.cancel_pending_charges(
            fee.id,
            actor_id,
            "Mensalidade liquidada por outro recebimento.",
            except_id=charge.id if charge else None,
        )
        after = {**fee_public(fee).model_dump(mode="json"), "payment_id": payment.id}
        record_event(self.session, "monthly_fee", fee.id, "paid", actor_id, after, before, note)
        record_event(
            self.session,
            "payment",
            payment.id,
            "recorded",
            actor_id,
            {
                "monthly_fee_id": fee.id,
                "charge_id": payment.charge_id,
                "amount_cents": amount_cents,
                "method": payment.method,
                "is_simulated": payment.is_simulated,
            },
            reason=note,
        )
        return payment

    def settle_simulated(self, data: SimulatedReceipt):
        """Internal test helper. HTTP confirmations use the durable webhook inbox."""
        get_pix_provider()
        with write_transaction(self.session):
            first = required(self.repository.charge(str(data.charge_id)), "Cobrança")
            fee = required(
                BillingRepository(self.session).get(first.monthly_fee_id, lock=True), "Mensalidade"
            )
            charge = required(self.repository.charge(first.id, lock=True), "Cobrança")
            if charge.reference != data.reference:
                raise ApplicationError("invalid_reference", "Referência de teste inválida.", 409)
            self.settle_locked(
                fee,
                amount_cents=data.amount_cents,
                currency=data.currency,
                actor_id=None,
                note=SIMULATION_NOTICE,
                charge=charge,
                external_payment_id=data.external_payment_id,
            )
            output = fee_public(fee)
        return output
