from datetime import datetime
from typing import Literal

from pydantic import Field

from app.core.domain import Input, Output, Reason

FollowupStatus = Literal["pendente", "em_acompanhamento", "resolvido", "encerrado"]


class FollowupChange(Input):
    status: FollowupStatus
    expected_version: int = Field(strict=True, ge=1)
    note: Reason


class FollowupPublic(Output):
    id: str
    student_id: str
    student_name: str
    baseline_at: datetime
    detected_at: datetime
    status: FollowupStatus
    assigned_to: str | None
    last_note: str | None
    closed_at: datetime | None
    version: int


class ScanStatus(Output):
    enabled: bool
    activated_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    next_attempt_at: datetime | None = None
    consecutive_failures: int = 0


class ScanRunPublic(Output):
    id: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    processed: int
    detected: int
    error_code: str | None
