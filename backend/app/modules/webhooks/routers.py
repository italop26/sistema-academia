from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.dependencies import Admin, BusinessSession
from app.core.domain import ReasonRequest, required
from app.modules.auth.dependencies import require_admin
from app.modules.payments.providers import SIMULATION_NOTICE
from app.modules.webhooks.auth import authenticated_test_event
from app.modules.webhooks.repositories import WebhookRepository
from app.modules.webhooks.schemas import EventPublic, EventReceipt, SimulatedEvent
from app.modules.webhooks.services import WebhookService

router = APIRouter(tags=["Simulated Pix webhook"])
admin_router = APIRouter(
    prefix="/admin/pix/events", tags=["Pix events"], dependencies=[Depends(require_admin)]
)


@router.post("/webhooks/pix/simulated", response_model=EventReceipt)
def receive(
    data: Annotated[SimulatedEvent, Depends(authenticated_test_event)], session: BusinessSession
):
    service = WebhookService(WebhookRepository(session))
    event, duplicate = service.receive(data)
    if event.status == "received":
        event = service.process(event.id)
    receipt = EventReceipt(
        id=event.id,
        external_event_id=event.external_event_id,
        status=event.status,
        duplicate=duplicate,
        simulation_notice=SIMULATION_NOTICE,
        error_code=event.last_error_code,
    )
    # 200 = processed/ignored; 202 = durably stored but requires retry/review.
    return JSONResponse(
        receipt.model_dump(mode="json"),
        status_code=202 if event.status in {"failed", "rejected"} else 200,
    )


@admin_router.get("", response_model=list[EventPublic])
def listing(
    session: BusinessSession,
    status: Literal["received", "processed", "ignored", "rejected", "failed"] | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    return WebhookRepository(session).list(status, offset, limit)


@admin_router.get("/{event_id}", response_model=EventPublic)
def detail(event_id: UUID, session: BusinessSession):
    return required(WebhookRepository(session).get(str(event_id)), "Evento")


@admin_router.post("/{event_id}/retry", response_model=EventPublic)
def retry(event_id: UUID, data: ReasonRequest, session: BusinessSession, actor: Admin):
    return WebhookService(WebhookRepository(session)).process(str(event_id), actor.id, data.reason)
