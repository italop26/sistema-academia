from datetime import date, datetime
from typing import Literal

from app.core.domain import Output

ReminderStatus = Literal["pending", "retry_wait", "sent", "exhausted", "suppressed"]


class ReminderPublic(Output):
    id: str
    monthly_fee_id: str
    rule_key: str
    status: ReminderStatus
    attempt_count: int
    cycle_attempts: int
    retry_cycles: int
    publication_failures: int
    next_attempt_at: datetime | None
    lease_until: datetime | None
    last_error_code: str | None
    suppression_reason: str | None
    receipt: str | None
    message: str | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    student_id: str | None = None
    student_name: str | None = None
    competence: str | None = None
    due_on: date | None = None
    amount_cents: int | None = None
    is_simulated: Literal[True] = True


class AttemptPublic(Output):
    id: str
    reminder_id: str
    number: int
    outcome: str
    error_code: str | None
    created_at: datetime
