from datetime import date, datetime
from uuid import UUID

from app.core.domain import Input, Output


class CheckInCreate(Input):
    student_id: UUID
    enrollment_id: UUID
    idempotency_key: UUID


class CheckInPublic(Output):
    id: str
    student_id: str
    enrollment_id: str
    actor_id: str
    occurred_at: datetime
    local_day: date


class AttendanceSummary(Output):
    student_id: str
    last_visit: datetime | None
    total_visits: int
