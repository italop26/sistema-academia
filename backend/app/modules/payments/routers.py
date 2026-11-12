from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import Admin, BusinessSession
from app.core.domain import required
from app.modules.auth.dependencies import require_admin
from app.modules.payments.repositories import PaymentRepository
from app.modules.payments.schemas import ChargeCreate, ChargePublic
from app.modules.payments.services import ChargeService, charge_public

router = APIRouter(
    prefix="/admin/pix/charges", tags=["Pix simulation"], dependencies=[Depends(require_admin)]
)


@router.post("", response_model=ChargePublic)
def create(data: ChargeCreate, session: BusinessSession, actor: Admin):
    return ChargeService(PaymentRepository(session)).create(data, actor.id)


@router.get("", response_model=list[ChargePublic])
def listing(
    monthly_fee_id: UUID,
    session: BusinessSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    return [
        charge_public(item)
        for item in PaymentRepository(session).charges(str(monthly_fee_id), offset, limit)
    ]


@router.get("/{charge_id}", response_model=ChargePublic)
def detail(charge_id: UUID, session: BusinessSession):
    return charge_public(required(PaymentRepository(session).charge(str(charge_id)), "Cobrança"))
