from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.config import get_settings
from app.core.dependencies import Admin, BusinessSession
from app.core.errors import ApplicationError
from app.modules.absence.followups import FollowupService, public
from app.modules.absence.models import AbsenceScanRun
from app.modules.absence.repositories import AbsenceRepository
from app.modules.absence.schemas import (
    FollowupChange,
    FollowupPublic,
    FollowupStatus,
    ScanRunPublic,
    ScanStatus,
)
from app.modules.absence.services import scan_absence
from app.modules.auth.dependencies import require_admin

router = APIRouter(prefix="/admin/absence", tags=["Absence"], dependencies=[Depends(require_admin)])


@router.get("/detections", response_model=list[FollowupPublic])
def listing(
    session: BusinessSession,
    status: FollowupStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
):
    return [
        public(row, name) for row, name in AbsenceRepository(session).listing(status, offset, limit)
    ]


@router.post("/detections/{detection_id}/status", response_model=FollowupPublic)
def change(detection_id: UUID, data: FollowupChange, session: BusinessSession, actor: Admin):
    return FollowupService(AbsenceRepository(session)).change(str(detection_id), data, actor.id)


@router.get("/status", response_model=ScanStatus)
def status(session: BusinessSession):
    state = AbsenceRepository(session).state()
    return (
        ScanStatus(
            enabled=get_settings().absence_tracking_enabled,
            **{
                field: getattr(state, field)
                for field in ScanStatus.model_fields
                if field != "enabled"
            },
        )
        if state
        else ScanStatus(enabled=get_settings().absence_tracking_enabled)
    )


@router.get("/runs", response_model=list[ScanRunPublic])
def runs(
    session: BusinessSession, offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=100)
):
    return session.scalars(
        select(AbsenceScanRun)
        .order_by(
            AbsenceScanRun.started_at.desc(),
            AbsenceScanRun.id,
        )
        .offset(offset)
        .limit(limit)
    ).all()


@router.post("/scan")
def scan(session: BusinessSession):
    if not get_settings().absence_tracking_enabled:
        raise ApplicationError("absence_disabled", "Acompanhamento de ausência desativado.", 409)
    return scan_absence(session.get_bind())
