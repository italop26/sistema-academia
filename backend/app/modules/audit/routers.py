from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_business_session
from app.core.domain import Output
from app.modules.audit.repositories import list_events
from app.modules.auth.dependencies import require_admin

router = APIRouter(prefix="/admin/history", tags=["History"], dependencies=[Depends(require_admin)])


class EventPublic(Output):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_id: str | None
    actor_type: Literal["admin", "system"]
    reason: str | None
    before: dict | None
    after: dict
    created_at: datetime


@router.get("", response_model=list[EventPublic])
def history(
    entity_type: Literal[
        "student",
        "check_in",
        "absence_detection",
        "plan",
        "enrollment",
        "monthly_fee",
        "charge",
        "payment",
        "webhook_event",
        "reminder",
    ],
    entity_id: UUID,
    session: Annotated[Session, Depends(get_business_session)],
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    return list_events(session, entity_type, str(entity_id), offset, limit)
