from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import Admin, BusinessSession
from app.core.domain import ReasonRequest, required
from app.core.errors import ApplicationError
from app.modules.auth.dependencies import require_admin
from app.modules.billing.repositories import BillingRepository
from app.modules.billing.schemas import (
    FeePublic,
    GenerateFee,
    PaymentCreate,
    PaymentPublic,
    parse_competence,
)
from app.modules.billing.services import BillingService, fee_public

router = APIRouter(
    prefix="/admin/monthly-fees", tags=["Monthly fees"], dependencies=[Depends(require_admin)]
)


@router.post("/generate", response_model=FeePublic)
def generate(data: GenerateFee, session: BusinessSession, actor: Admin):
    return BillingService(BillingRepository(session)).generate(data, actor.id)


@router.get("", response_model=list[FeePublic])
def listing(
    session: BusinessSession,
    student_id: UUID | None = None,
    competence: str | None = Query(None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    if competence and competence.startswith("0000"):
        raise ApplicationError("invalid_competence", "Competência inválida.", 422)
    fees = BillingRepository(session).list(
        str(student_id) if student_id else None,
        parse_competence(competence) if competence else None,
        offset,
        limit,
    )
    return [fee_public(fee) for fee in fees]


@router.get("/{fee_id}", response_model=FeePublic)
def detail(fee_id: UUID, session: BusinessSession):
    return fee_public(required(BillingRepository(session).get(str(fee_id)), "Mensalidade"))


@router.post("/{fee_id}/pay", response_model=FeePublic)
def pay(fee_id: UUID, data: PaymentCreate, session: BusinessSession, actor: Admin):
    return BillingService(BillingRepository(session)).pay(str(fee_id), data, actor.id)


@router.post("/{fee_id}/cancel", response_model=FeePublic)
def cancel(fee_id: UUID, data: ReasonRequest, session: BusinessSession, actor: Admin):
    return BillingService(BillingRepository(session)).cancel(str(fee_id), data, actor.id)


@router.get("/{fee_id}/payment", response_model=PaymentPublic)
def payment(fee_id: UUID, session: BusinessSession):
    return required(BillingRepository(session).payment(str(fee_id)), "Pagamento")
