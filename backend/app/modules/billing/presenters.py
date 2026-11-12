from datetime import date

from app.core.domain import local_today
from app.modules.billing.models import MonthlyFee
from app.modules.billing.schemas import FeePublic
from app.modules.payments.providers import SIMULATION_NOTICE


def fee_public(fee: MonthlyFee, today: date | None = None) -> FeePublic:
    status = fee.status
    if status == "pendente" and fee.due_on < (today or local_today()):
        status = "vencida"
    payment = fee.payment if fee.status == "paga" else None
    simulated = payment.is_simulated if payment else False
    return FeePublic(
        id=fee.id,
        enrollment_id=fee.enrollment_id,
        student_id=fee.enrollment.student_id,
        student_name=fee.enrollment.student.name,
        competence=fee.competence.isoformat()[:7],
        due_on=fee.due_on,
        amount_cents=fee.amount_cents,
        status=status,
        completed=fee.status == "paga",
        paid_at=fee.paid_at,
        created_at=fee.created_at,
        payment_method=payment.method if payment else None,
        is_simulated=simulated,
        simulation_notice=SIMULATION_NOTICE if simulated else None,
    )
