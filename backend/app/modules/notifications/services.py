import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_engine, write_transaction
from app.core.domain import local_today, required, utcnow
from app.core.errors import ApplicationError
from app.modules.audit.repositories import record_event
from app.modules.billing.repositories import BillingRepository
from app.modules.notifications.models import Reminder, ReminderAttempt
from app.modules.notifications.repositories import ACTIVE_STATES, RULE_KEY, NotificationRepository
from app.modules.notifications.schemas import ReminderPublic
from app.modules.notifications.sender import ReminderMessage, SimulatedReminderSender
from app.modules.payments.repositories import PaymentRepository
from app.modules.payments.services import as_utc

logger = logging.getLogger(__name__)
RETRY_DELAYS = (60, 300)
MAX_ATTEMPTS = 3
MAX_MANUAL_CYCLES = 3


def snapshot(reminder: Reminder):
    return {
        "status": reminder.status,
        "attempt_count": reminder.attempt_count,
        "cycle_attempts": reminder.cycle_attempts,
        "retry_cycles": reminder.retry_cycles,
        "publication_failures": reminder.publication_failures,
        "error_code": reminder.last_error_code,
        "suppression_reason": reminder.suppression_reason,
    }


def clear_dispatch(reminder: Reminder):
    reminder.dispatch_token = None
    reminder.lease_until = None
    reminder.updated_at = utcnow()


class NotificationService:
    def __init__(self, repository: NotificationRepository):
        self.repository = repository
        self.session = repository.session

    def suppression(self, fee):
        if fee.status == "paga" or PaymentRepository(self.session).payment(fee.id):
            return "paid"
        if fee.status == "cancelada":
            return "cancelled"
        if fee.status != "pendente" or fee.due_on >= local_today():
            return "not_overdue"
        return None

    def plan(self, fee_id: str):
        with write_transaction(self.session):
            fee = required(BillingRepository(self.session).get(fee_id, lock=True), "Mensalidade")
            if self.suppression(fee) or self.repository.for_fee(fee.id):
                return False
            reminder = Reminder(monthly_fee_id=fee.id, rule_key=RULE_KEY)
            self.session.add(reminder)
            self.session.flush()
            record_event(
                self.session,
                "reminder",
                reminder.id,
                "planned",
                None,
                {**snapshot(reminder), "monthly_fee_id": fee.id, "is_simulated": True},
            )
        return True

    def reserve(self, reminder_id: str):
        with write_transaction(self.session):
            reminder = self.repository.get(reminder_id, lock=True)
            now = utcnow()
            if (
                not reminder
                or reminder.status not in ACTIVE_STATES
                or reminder.next_attempt_at is None
                or as_utc(reminder.next_attempt_at) > now
                or (reminder.lease_until and as_utc(reminder.lease_until) > now)
            ):
                return None
            token = str(uuid4())
            reminder.dispatch_token = token
            reminder.lease_until = now + timedelta(
                seconds=get_settings().notification_dispatch_lease_seconds,
            )
            reminder.updated_at = now
        return token

    def publication_failed(self, reminder_id: str, token: str):
        with write_transaction(self.session):
            reminder = self.repository.get(reminder_id, lock=True)
            if (
                not reminder
                or reminder.dispatch_token != token
                or reminder.status not in ACTIVE_STATES
            ):
                return
            reminder.publication_failures += 1
            reminder.last_error_code = "broker_unavailable"
            reminder.next_attempt_at = utcnow() + timedelta(seconds=60)
            clear_dispatch(reminder)
            record_event(
                self.session,
                "reminder",
                reminder.id,
                "publication_failed",
                None,
                snapshot(reminder),
            )

    def _locked(self, reminder_id: str):
        first = self.repository.get(reminder_id)
        if not first:
            return None, None
        fee = required(
            BillingRepository(self.session).get(first.monthly_fee_id, lock=True), "Mensalidade"
        )
        return fee, self.repository.get(reminder_id, lock=True)

    def _suppress(
        self, reminder: Reminder, why: str, actor_id: str | None = None, reason: str | None = None
    ):
        before = snapshot(reminder)
        reminder.status = "suppressed"
        reminder.suppression_reason = why
        reminder.next_attempt_at = None
        reminder.last_error_code = None
        clear_dispatch(reminder)
        record_event(
            self.session,
            "reminder",
            reminder.id,
            "suppressed",
            actor_id,
            snapshot(reminder),
            before,
            reason,
        )

    def deliver(self, reminder_id: str, token: str, sender=None):
        if not get_settings().financial_automation_enabled:
            return "disabled"
        try:
            with write_transaction(self.session):
                fee, reminder = self._locked(reminder_id)
                if not reminder:
                    return "missing"
                if (
                    reminder.status not in ACTIVE_STATES
                    or reminder.dispatch_token != token
                    or not reminder.lease_until
                    or as_utc(reminder.lease_until) <= utcnow()
                ):
                    return "stale"
                if not reminder.next_attempt_at or as_utc(reminder.next_attempt_at) > utcnow():
                    return "not_due"
                why = self.suppression(fee)
                if why:
                    self._suppress(reminder, why)
                    return "suppressed"
                if reminder.cycle_attempts >= MAX_ATTEMPTS:
                    return "exhausted"
                result = (sender or SimulatedReminderSender()).send(
                    ReminderMessage(
                        reminder_id=reminder.id,
                        monthly_fee_id=fee.id,
                        amount_cents=fee.amount_cents,
                        due_on=fee.due_on,
                    )
                )
                before = snapshot(reminder)
                reminder.attempt_count += 1
                reminder.cycle_attempts += 1
                reminder.status = "sent"
                reminder.receipt, reminder.message = result.receipt, result.message
                reminder.sent_at = utcnow()
                reminder.next_attempt_at = None
                reminder.last_error_code = None
                clear_dispatch(reminder)
                self.session.add(
                    ReminderAttempt(
                        reminder_id=reminder.id, number=reminder.attempt_count, outcome="sent"
                    )
                )
                record_event(
                    self.session,
                    "reminder",
                    reminder.id,
                    "simulated_sent",
                    None,
                    {**snapshot(reminder), "receipt": reminder.receipt},
                    before,
                )
            return "sent"
        except Exception as exc:
            logger.error("Falha na simulação de lembrete", extra={"error_type": type(exc).__name__})
            return self._send_failed(reminder_id, token)

    def _send_failed(self, reminder_id: str, token: str):
        with write_transaction(self.session):
            fee, reminder = self._locked(reminder_id)
            if (
                not reminder
                or reminder.status not in ACTIVE_STATES
                or reminder.dispatch_token != token
            ):
                return "stale"
            before = snapshot(reminder)
            reminder.attempt_count += 1
            reminder.cycle_attempts += 1
            self.session.add(
                ReminderAttempt(
                    reminder_id=reminder.id,
                    number=reminder.attempt_count,
                    outcome="failed",
                    error_code="simulated_send_failed",
                )
            )
            reminder.last_error_code = "simulated_send_failed"
            why = self.suppression(fee)
            if why:
                self._suppress(reminder, why)
            elif reminder.cycle_attempts >= MAX_ATTEMPTS:
                reminder.status, reminder.next_attempt_at = "exhausted", None
            else:
                reminder.status = "retry_wait"
                reminder.next_attempt_at = utcnow() + timedelta(
                    seconds=RETRY_DELAYS[reminder.cycle_attempts - 1],
                )
            clear_dispatch(reminder)
            record_event(
                self.session,
                "reminder",
                reminder.id,
                "send_failed",
                None,
                snapshot(reminder),
                before,
            )
            result = reminder.status
        return result

    def retry(self, reminder_id: str, actor_id: str, reason: str):
        if not get_settings().financial_automation_enabled:
            raise ApplicationError("automation_disabled", "Automação financeira desativada.", 409)
        with write_transaction(self.session):
            fee, reminder = self._locked(reminder_id)
            required(reminder, "Lembrete")
            if reminder.status != "exhausted" or reminder.retry_cycles >= MAX_MANUAL_CYCLES:
                raise ApplicationError(
                    "reminder_not_retryable", "Lembrete não permite nova tentativa.", 409
                )
            why = self.suppression(fee)
            if why:
                self._suppress(reminder, why, actor_id, reason)
            else:
                before = snapshot(reminder)
                reminder.status = "pending"
                reminder.cycle_attempts = 0
                reminder.retry_cycles += 1
                reminder.next_attempt_at = utcnow()
                reminder.last_error_code = None
                clear_dispatch(reminder)
                record_event(
                    self.session,
                    "reminder",
                    reminder.id,
                    "retry_requested",
                    actor_id,
                    snapshot(reminder),
                    before,
                    reason,
                )
            result = ReminderPublic.model_validate(reminder)
        return result


def scan_overdue(engine=None):
    settings = get_settings()
    if not settings.financial_automation_enabled:
        return {"enabled": False, "examined": 0, "created": 0}
    engine = engine or get_engine()
    with Session(engine) as session:
        ids = NotificationRepository(session).overdue_ids(
            local_today(), settings.notification_batch_size
        )
    created = 0
    for fee_id in ids:
        with Session(engine, expire_on_commit=False) as session:
            created += int(NotificationService(NotificationRepository(session)).plan(fee_id))
    return {"enabled": True, "examined": len(ids), "created": created}


def dispatch_pending(engine=None, publisher=None):
    settings = get_settings()
    if not settings.financial_automation_enabled:
        return {"enabled": False, "published": 0, "failed": 0}
    if publisher is None:
        from app.modules.notifications.tasks import deliver_reminder

        def publisher(reminder_id, token):
            deliver_reminder.apply_async(
                args=[reminder_id, token],
                retry=False,
                expires=settings.notification_dispatch_lease_seconds,
            )

    engine = engine or get_engine()
    with Session(engine) as session:
        ids = NotificationRepository(session).due_ids(utcnow(), settings.notification_batch_size)
    published, failed = 0, 0
    for reminder_id in ids:
        with Session(engine, expire_on_commit=False) as session:
            service = NotificationService(NotificationRepository(session))
            token = service.reserve(reminder_id)
            if not token:
                continue
            try:
                publisher(reminder_id, token)
                published += 1
            except Exception as exc:
                logger.error(
                    "Publicação de lembrete indisponível", extra={"error_type": type(exc).__name__}
                )
                service.publication_failed(reminder_id, token)
                failed += 1
    return {"enabled": True, "published": published, "failed": failed}
