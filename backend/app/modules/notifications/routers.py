from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.dependencies import Admin, BusinessSession
from app.core.domain import ReasonRequest, required
from app.modules.auth.dependencies import require_admin
from app.modules.notifications.repositories import NotificationRepository
from app.modules.notifications.schemas import AttemptPublic, ReminderPublic, ReminderStatus
from app.modules.notifications.sender import SIMULATION_NOTICE
from app.modules.notifications.services import NotificationService, dispatch_pending, scan_overdue

router = APIRouter(
    prefix="/admin/notifications",
    tags=["Simulated reminders"],
    dependencies=[Depends(require_admin)],
)


@router.get("/summary")
def summary(session: BusinessSession):
    counts = NotificationRepository(session).summary()
    return {
        "enabled": get_settings().financial_automation_enabled,
        "is_simulated": True,
        "simulation_notice": SIMULATION_NOTICE,
        "counts": {
            status: counts.get(status, 0)
            for status in ("pending", "retry_wait", "sent", "exhausted", "suppressed")
        },
    }


@router.post("/scan")
def scan(session: BusinessSession):
    result = scan_overdue(session.get_bind())
    result["dispatch"] = dispatch_pending(session.get_bind())
    return result


@router.get("/reminders", response_model=list[ReminderPublic])
def listing(
    session: BusinessSession,
    student_id: UUID | None = None,
    status: ReminderStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    rows = NotificationRepository(session).list(
        str(student_id) if student_id else None, status, offset, limit
    )
    return [
        ReminderPublic.model_validate(reminder).model_copy(
            update={
                "student_name": name,
                "student_id": student_id,
                "competence": competence.isoformat()[:7],
                "due_on": due_on,
                "amount_cents": amount_cents,
            }
        )
        for reminder, name, student_id, competence, due_on, amount_cents in rows
    ]


@router.get("/reminders/{reminder_id}", response_model=ReminderPublic)
def detail(reminder_id: UUID, session: BusinessSession):
    return required(NotificationRepository(session).get(str(reminder_id)), "Lembrete")


@router.get("/reminders/{reminder_id}/attempts", response_model=list[AttemptPublic])
def attempts(reminder_id: UUID, session: BusinessSession):
    required(NotificationRepository(session).get(str(reminder_id)), "Lembrete")
    return NotificationRepository(session).attempts(str(reminder_id))


@router.post("/reminders/{reminder_id}/retry", response_model=ReminderPublic)
def retry(reminder_id: UUID, data: ReasonRequest, session: BusinessSession, actor: Admin):
    return NotificationService(NotificationRepository(session)).retry(
        str(reminder_id), actor.id, data.reason
    )
