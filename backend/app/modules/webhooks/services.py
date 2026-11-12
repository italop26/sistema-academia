import hashlib
import json
import logging
from datetime import timedelta

from app.core.database import write_transaction
from app.core.domain import required, utcnow
from app.core.errors import ApplicationError
from app.modules.audit.repositories import record_event
from app.modules.billing.repositories import BillingRepository
from app.modules.payments.providers import SIMULATED_PROVIDER, SIMULATION_NOTICE, get_pix_provider
from app.modules.payments.repositories import PaymentRepository
from app.modules.payments.services import SettlementService, as_utc, charge_public
from app.modules.webhooks.models import WebhookEvent
from app.modules.webhooks.repositories import WebhookRepository
from app.modules.webhooks.schemas import EventPublic, SimulatedEvent

BUSINESS_ERRORS = {
    "not_found",
    "invalid_charge",
    "invalid_reference",
    "amount_mismatch",
    "payment_conflict",
    "invalid_transition",
    "invalid_event_time",
    "late_payment",
    "record_conflict",
}
logger = logging.getLogger(__name__)


def snapshot(event: WebhookEvent):
    return {
        "status": event.status,
        "attempt_count": event.attempt_count,
        "result_code": event.result_code,
        "payment_id": event.payment_id,
        "error_code": event.last_error_code,
    }


class WebhookService:
    def __init__(self, repository: WebhookRepository):
        self.repository = repository
        self.session = repository.session

    def receive(self, data: SimulatedEvent):
        get_pix_provider()
        payload = data.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        # PostgreSQL may race on a previously absent event. Retry the insert conflict once,
        # then compare with the durable winner under its row lock.
        for attempt in range(2):
            try:
                result, duplicate, conflict = self._receive_once(data, payload, digest)
                break
            except ApplicationError as exc:
                if exc.code != "record_conflict" or attempt:
                    raise
        if conflict:
            raise ApplicationError(
                "event_content_conflict", "Identificador de evento reutilizado.", 409
            )
        return result, duplicate

    def _receive_once(self, data: SimulatedEvent, payload: dict, digest: str):
        with write_transaction(self.session):
            event = self.repository.by_external_id(SIMULATED_PROVIDER, str(data.event_id))
            duplicate = event is not None
            conflict = False
            if event:
                event.delivery_count += 1
                event.last_received_at = utcnow()
                conflict = event.content_hash != digest
                if conflict:
                    event.conflict_count += 1
                    event.last_conflict_hash = digest
                    record_event(
                        self.session,
                        "webhook_event",
                        event.id,
                        "delivery_conflict",
                        None,
                        {"conflict_count": event.conflict_count, "content_hash": digest},
                    )
            else:
                event = WebhookEvent(
                    provider=SIMULATED_PROVIDER,
                    external_event_id=str(data.event_id),
                    payload=payload,
                    content_hash=digest,
                )
                self.session.add(event)
                self.session.flush()
                record_event(
                    self.session,
                    "webhook_event",
                    event.id,
                    "received",
                    None,
                    {
                        "external_event_id": event.external_event_id,
                        "content_hash": digest,
                        "is_simulated": True,
                    },
                )
            self.session.flush()
            output = EventPublic.model_validate(event)
        return output, duplicate, conflict

    def process(self, event_id: str, actor_id: str | None = None, reason: str | None = None):
        get_pix_provider()
        try:
            with write_transaction(self.session):
                event = self.repository.get(event_id, lock=True)
                if event is None:
                    raise ApplicationError("event_not_found", "Evento não encontrado.", 404)
                if event.status not in {"received", "failed"}:
                    if actor_id:
                        raise ApplicationError(
                            "event_not_retryable", "Evento não permite nova tentativa.", 409
                        )
                    return EventPublic.model_validate(event)
                before = snapshot(event)
                event.attempt_count += 1
                event.last_attempt_at = utcnow()
                self._apply(event)
                event.last_error_code = None
                event.processed_at = utcnow()
                record_event(
                    self.session,
                    "webhook_event",
                    event.id,
                    "retried" if actor_id else "processed",
                    actor_id,
                    snapshot(event),
                    before,
                    reason,
                )
                self.session.flush()
                output = EventPublic.model_validate(event)
            return output
        except ApplicationError as exc:
            if exc.code in {"event_not_found", "event_not_retryable"}:
                raise
            rejected = exc.status_code < 500 and exc.code in BUSINESS_ERRORS
            code = exc.code if rejected else "processing_failed"
            return self._record_failure(event_id, code, rejected, actor_id, reason)
        except Exception as exc:
            # The transaction has rolled back; keep only a safe code, never exception text,
            # provider payloads, signature or secrets. The durable event supports manual retry.
            logger.error(
                "Falha no processamento do webhook de teste",
                extra={"error_type": type(exc).__name__},
            )
            return self._record_failure(event_id, "processing_failed", False, actor_id, reason)

    def _record_failure(
        self, event_id: str, code: str, rejected: bool, actor_id: str | None, reason: str | None
    ):
        with write_transaction(self.session):
            event = required(self.repository.get(event_id, lock=True), "Evento")
            before = snapshot(event)
            event.attempt_count += 1
            event.last_attempt_at = utcnow()
            # Another worker may have completed it after our rollback. Preserve its terminal state.
            if event.status in {"received", "failed"}:
                event.status = "rejected" if rejected else "failed"
                event.last_error_code = code
                event.result_code = None
                event.processed_at = utcnow() if rejected else None
            record_event(
                self.session,
                "webhook_event",
                event.id,
                "retry_failed" if actor_id else "processing_failed",
                actor_id,
                {**snapshot(event), "attempt_error_code": code},
                before,
                reason,
            )
            self.session.flush()
            output = EventPublic.model_validate(event)
        return output

    def _apply(self, event: WebhookEvent):
        data = SimulatedEvent.model_validate(event.payload)
        payments = PaymentRepository(self.session)
        first = required(payments.charge(str(data.charge_id)), "Cobrança")
        # All financial operations take locks in fee -> charge order.
        fee = required(
            BillingRepository(self.session).get(first.monthly_fee_id, lock=True), "Mensalidade"
        )
        charge = required(payments.charge(first.id, lock=True), "Cobrança")
        if charge.provider != SIMULATED_PROVIDER or not charge.is_simulated:
            raise ApplicationError("invalid_charge", "Cobrança não simulada.", 409)
        if data.reference != charge.reference:
            raise ApplicationError("invalid_reference", "Referência incompatível.", 409)
        if (
            data.amount_cents != charge.amount_cents
            or data.amount_cents != fee.amount_cents
            or data.currency != charge.currency
            or data.currency != "BRL"
        ):
            raise ApplicationError("amount_mismatch", "Valor ou moeda incompatível.", 409)
        if data.occurred_at < as_utc(charge.created_at) or data.occurred_at > utcnow() + timedelta(
            seconds=60
        ):
            raise ApplicationError("invalid_event_time", "Data do evento incompatível.", 409)
        event.charge_id = charge.id
        if data.event_type == "payment.confirmed":
            if data.occurred_at > as_utc(charge.expires_at):
                raise ApplicationError("late_payment", "Confirmação posterior à expiração.", 409)
            previous_payment = payments.payment(fee.id)
            payment = SettlementService(self.session).settle_locked(
                fee,
                amount_cents=data.amount_cents,
                currency=data.currency,
                actor_id=None,
                note=SIMULATION_NOTICE,
                charge=charge,
                external_payment_id=data.external_payment_id,
            )
            event.payment_id = payment.id
            event.status = "ignored" if previous_payment else "processed"
            event.result_code = "already_applied" if previous_payment else "payment_applied"
        elif data.event_type == "charge.pending":
            event.status, event.result_code = "ignored", "status_noop"
        elif fee.status == "paga" or charge.status in {"paid", "cancelled"}:
            event.status, event.result_code = "ignored", "terminal_status_preserved"
        else:
            before = charge_public(charge).model_dump(mode="json")
            charge.status = "cancelled"
            record_event(
                self.session,
                "charge",
                charge.id,
                "cancelled",
                None,
                charge_public(charge).model_dump(mode="json"),
                before,
                SIMULATION_NOTICE,
            )
            event.status, event.result_code = "processed", "charge_cancelled"
