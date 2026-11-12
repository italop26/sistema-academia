from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent


def record_event(
    session: Session,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: str | None,
    after: dict,
    before: dict | None = None,
    reason: str | None = None,
) -> None:
    # Uses the caller's transaction; history and business data commit or roll back together.
    session.add(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            actor_type="admin" if actor_id is not None else "system",
            before=before,
            after=after,
            reason=reason,
        )
    )


def list_events(session: Session, entity_type: str, entity_id: str, offset: int, limit: int):
    return session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == entity_type,
            AuditEvent.entity_id == entity_id,
        )
        .order_by(AuditEvent.created_at, AuditEvent.id)
        .offset(offset)
        .limit(limit)
    ).all()
