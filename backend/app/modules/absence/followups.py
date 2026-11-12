"""Small synchronous workflow, sharing the caller's transaction for check-in resolution."""

from app.core.database import write_transaction
from app.core.domain import required, utcnow
from app.core.errors import ApplicationError
from app.modules.absence.models import AbsenceDetection
from app.modules.absence.repositories import OPEN_STATES, AbsenceRepository
from app.modules.absence.schemas import FollowupChange, FollowupPublic
from app.modules.audit.repositories import record_event
from app.modules.students.repositories import StudentRepository


def snapshot(row):
    return {
        "status": row.status,
        "assigned_to": row.assigned_to,
        "last_note": row.last_note,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "version": row.version,
    }


def transition(session, row, status, note, now, actor_id=None):
    before = snapshot(row)
    row.status, row.last_note = status, note
    if status == "em_acompanhamento":
        row.assigned_to = actor_id
    elif status == "pendente":
        row.assigned_to = None
    row.closed_at = now if status in ("resolvido", "encerrado") else None
    row.version += 1
    record_event(
        session,
        "absence_detection",
        row.id,
        "status_changed",
        actor_id,
        snapshot(row),
        before,
        note,
    )


def resolve_on_check_in(session, visit, actor_id):
    row = AbsenceRepository(session).open_for_student(visit.student_id)
    if row:
        from app.modules.absence.services import as_utc

        if as_utc(visit.occurred_at) >= as_utc(row.detected_at):
            transition(
                session,
                row,
                "resolvido",
                "Retorno registrado por check-in.",
                visit.occurred_at,
                actor_id,
            )


def reconcile(session, student_id, eligible, visit, now):
    row = AbsenceRepository(session).open_for_student(student_id)
    if not row:
        return
    from app.modules.absence.services import as_utc

    if visit and as_utc(visit.occurred_at) >= as_utc(row.detected_at):
        transition(session, row, "resolvido", "Retorno confirmado na verificação.", now)
    elif eligible is None or eligible > as_utc(row.baseline_at):
        transition(session, row, "encerrado", "Elegibilidade de frequência alterada.", now)


def public(row, name):
    return FollowupPublic.model_validate(
        {
            **{
                field: getattr(row, field)
                for field in FollowupPublic.model_fields
                if field != "student_name"
            },
            "student_name": name,
        }
    )


class FollowupService:
    def __init__(self, repository: AbsenceRepository):
        self.repository = repository

    def change(self, detection_id: str, data: FollowupChange, actor_id: str):
        session = self.repository.session
        with write_transaction(session):
            row = required(session.get(AbsenceDetection, detection_id), "Acompanhamento")
            student = required(StudentRepository(session).get(row.student_id, lock=True), "Aluno")
            if row.version != data.expected_version:
                if (
                    row.version == data.expected_version + 1
                    and row.status == data.status
                    and row.last_note == data.note
                    and (row.status != "em_acompanhamento" or row.assigned_to == actor_id)
                ):
                    return public(row, student.name)
                raise ApplicationError("followup_changed", "O acompanhamento foi atualizado.", 409)
            if row.status not in OPEN_STATES:
                raise ApplicationError("invalid_transition", "Acompanhamento já finalizado.", 409)
            transition(session, row, data.status, data.note, utcnow(), actor_id)
            result = public(row, student.name)
        return result
