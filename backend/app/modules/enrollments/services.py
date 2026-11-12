from sqlalchemy import select

from app.core.database import write_transaction
from app.core.domain import ReasonRequest, required, utcnow
from app.core.errors import ApplicationError
from app.modules.audit.repositories import record_event
from app.modules.enrollments.models import Enrollment, EnrollmentSuspension
from app.modules.enrollments.repositories import EnrollmentRepository
from app.modules.enrollments.schemas import (
    EnrollmentCreate,
    EnrollmentPublic,
    SuspensionCreate,
    SuspensionPublic,
)
from app.modules.plans.repositories import PlanRepository
from app.modules.students.repositories import StudentRepository


class EnrollmentService:
    def __init__(self, repository: EnrollmentRepository):
        self.repository = repository

    def create(self, data: EnrollmentCreate, actor_id: str):
        session = self.repository.session
        with write_transaction(session):
            student = required(
                StudentRepository(session).get(str(data.student_id), lock=True), "Aluno"
            )
            plan = required(PlanRepository(session).get(str(data.plan_id), lock=True), "Plano")
            if not student.is_active or not plan.is_active:
                raise ApplicationError("inactive_record", "Aluno e plano devem estar ativos.", 409)
            enrollment = Enrollment(
                **data.model_dump(exclude={"student_id", "plan_id"}),
                student_id=student.id,
                plan_id=plan.id,
                amount_cents=plan.monthly_amount_cents,
            )
            self.repository.add(enrollment)
            result = EnrollmentPublic.model_validate(enrollment)
            record_event(
                session,
                "enrollment",
                enrollment.id,
                "created",
                actor_id,
                result.model_dump(mode="json"),
            )
        return result

    def cancel(self, enrollment_id: str, data: ReasonRequest, actor_id: str):
        with write_transaction(self.repository.session):
            enrollment = required(self.repository.get(enrollment_id, lock=True), "Matrícula")
            before = EnrollmentPublic.model_validate(enrollment).model_dump(mode="json")
            if enrollment.status != "cancelada":
                enrollment.status = "cancelada"
                enrollment.cancelled_at = utcnow()
                record_event(
                    self.repository.session,
                    "enrollment",
                    enrollment.id,
                    "cancelled",
                    actor_id,
                    {**before, "status": "cancelada"},
                    before,
                    data.reason,
                )
            result = EnrollmentPublic.model_validate(enrollment)
        return result

    def suspend(self, enrollment_id: str, data: SuspensionCreate, actor_id: str):
        session = self.repository.session
        with write_transaction(session):
            enrollment = required(self.repository.get(enrollment_id, lock=True), "Matrícula")
            prior = session.scalar(
                select(EnrollmentSuspension).where(
                    EnrollmentSuspension.request_key == str(data.request_key)
                )
            )
            if prior:
                if prior.enrollment_id != enrollment_id or prior.reason != data.reason:
                    raise ApplicationError("idempotency_conflict", "Chave já utilizada.", 409)
                return SuspensionPublic.model_validate(prior)
            if enrollment.status != "ativa" or self.repository.open_suspension(enrollment_id):
                raise ApplicationError(
                    "invalid_transition", "Matrícula não permite suspensão.", 409
                )
            period = EnrollmentSuspension(
                enrollment_id=enrollment_id,
                request_key=str(data.request_key),
                starts_at=utcnow(),
                actor_id=actor_id,
                reason=data.reason,
            )
            session.add(period)
            session.flush()
            result = SuspensionPublic.model_validate(period)
            record_event(
                session,
                "enrollment",
                enrollment_id,
                "suspended",
                actor_id,
                result.model_dump(mode="json"),
                reason=data.reason,
            )
        return result

    def resume(self, enrollment_id: str, suspension_id: str, data: ReasonRequest, actor_id: str):
        session = self.repository.session
        with write_transaction(session):
            enrollment = required(self.repository.get(enrollment_id, lock=True), "Matrícula")
            period = required(session.get(EnrollmentSuspension, suspension_id), "Suspensão")
            if period.enrollment_id != enrollment_id:
                raise ApplicationError("record_not_found", "Suspensão não encontrada.", 404)
            if period.ends_at is None:
                if enrollment.status != "ativa":
                    raise ApplicationError("invalid_transition", "Matrícula cancelada.", 409)
                before = SuspensionPublic.model_validate(period).model_dump(mode="json")
                period.ends_at = utcnow()
                record_event(
                    session,
                    "enrollment",
                    enrollment_id,
                    "resumed",
                    actor_id,
                    SuspensionPublic.model_validate(period).model_dump(mode="json"),
                    before,
                    data.reason,
                )
            result = SuspensionPublic.model_validate(period)
        return result
