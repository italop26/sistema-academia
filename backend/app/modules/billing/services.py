from calendar import monthrange

from app.core.database import write_transaction
from app.core.domain import ReasonRequest, required
from app.core.errors import ApplicationError
from app.modules.audit.repositories import record_event
from app.modules.billing.models import MonthlyFee
from app.modules.billing.presenters import fee_public
from app.modules.billing.repositories import BillingRepository
from app.modules.billing.schemas import FeePublic, GenerateFee, PaymentCreate, parse_competence
from app.modules.enrollments.repositories import EnrollmentRepository
from app.modules.payments.services import SettlementService


class BillingService:
    def __init__(self, repository: BillingRepository):
        self.repository = repository

    def generate(self, data: GenerateFee, actor_id: str) -> FeePublic:
        session = self.repository.session
        competence = parse_competence(data.competence)
        with write_transaction(session):
            enrollment = required(
                EnrollmentRepository(session).get(str(data.enrollment_id), lock=True), "Matrícula"
            )
            # A retry returns the existing record, even after cancellation or payment.
            fee = self.repository.by_competence(enrollment.id, competence)
            if fee is not None:
                return fee_public(fee)
            month_end = competence.replace(day=monthrange(competence.year, competence.month)[1])
            if (
                enrollment.status != "ativa"
                or enrollment.starts_on > month_end
                or (enrollment.ends_on is not None and enrollment.ends_on < competence)
            ):
                raise ApplicationError(
                    "invalid_competence", "Competência fora da matrícula ativa.", 409
                )
            fee = MonthlyFee(
                enrollment_id=enrollment.id,
                competence=competence,
                due_on=competence.replace(day=min(enrollment.due_day, month_end.day)),
                amount_cents=enrollment.amount_cents,
            )
            self.repository.add(fee)
            result = fee_public(fee)
            record_event(
                session, "monthly_fee", fee.id, "issued", actor_id, result.model_dump(mode="json")
            )
        return result

    def pay(self, fee_id: str, data: PaymentCreate, actor_id: str) -> FeePublic:
        session = self.repository.session
        with write_transaction(session):
            fee = required(self.repository.get(fee_id, lock=True), "Mensalidade")
            SettlementService(session).settle_locked(
                fee,
                amount_cents=data.amount_cents,
                currency="BRL",
                actor_id=actor_id,
                note=data.note,
            )
            result = fee_public(fee)
        return result

    def cancel(self, fee_id: str, data: ReasonRequest, actor_id: str) -> FeePublic:
        with write_transaction(self.repository.session):
            fee = required(self.repository.get(fee_id, lock=True), "Mensalidade")
            if fee.status == "paga":
                raise ApplicationError(
                    "invalid_transition", "Mensalidade paga não pode ser cancelada.", 409
                )
            before = fee_public(fee).model_dump(mode="json")
            if fee.status != "cancelada":
                fee.status = "cancelada"
                SettlementService(self.repository.session).cancel_pending_charges(
                    fee.id,
                    actor_id,
                    data.reason,
                )
                record_event(
                    self.repository.session,
                    "monthly_fee",
                    fee.id,
                    "cancelled",
                    actor_id,
                    fee_public(fee).model_dump(mode="json"),
                    before,
                    data.reason,
                )
            result = fee_public(fee)
        return result
