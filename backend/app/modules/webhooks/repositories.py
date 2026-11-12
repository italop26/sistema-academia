from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.webhooks.models import WebhookEvent


class WebhookRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, event_id: str, lock: bool = False):
        query = select(WebhookEvent).where(WebhookEvent.id == event_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def by_external_id(self, provider: str, external_id: str):
        return self.session.scalar(
            select(WebhookEvent)
            .where(
                WebhookEvent.provider == provider,
                WebhookEvent.external_event_id == external_id,
            )
            .with_for_update()
        )

    def list(self, status: str | None, offset: int, limit: int):
        query = select(WebhookEvent)
        if status:
            query = query.where(WebhookEvent.status == status)
        return self.session.scalars(
            query.order_by(
                WebhookEvent.received_at.desc(),
                WebhookEvent.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
