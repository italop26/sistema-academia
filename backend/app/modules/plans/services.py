from app.core.database import write_transaction
from app.core.domain import ReasonRequest, required
from app.modules.audit.repositories import record_event
from app.modules.plans.models import Plan
from app.modules.plans.repositories import PlanRepository
from app.modules.plans.schemas import PlanCreate, PlanPublic


class PlanService:
    def __init__(self, repository: PlanRepository):
        self.repository = repository

    def create(self, data: PlanCreate, actor_id: str):
        with write_transaction(self.repository.session):
            plan = Plan(**data.model_dump())
            self.repository.add(plan)
            result = PlanPublic.model_validate(plan)
            record_event(
                self.repository.session,
                "plan",
                plan.id,
                "created",
                actor_id,
                result.model_dump(mode="json"),
            )
        return result

    def deactivate(self, plan_id: str, data: ReasonRequest, actor_id: str):
        with write_transaction(self.repository.session):
            plan = required(self.repository.get(plan_id, lock=True), "Plano")
            before = PlanPublic.model_validate(plan).model_dump(mode="json")
            if plan.is_active:
                plan.is_active = False
                record_event(
                    self.repository.session,
                    "plan",
                    plan.id,
                    "deactivated",
                    actor_id,
                    {**before, "is_active": False},
                    before,
                    data.reason,
                )
            result = PlanPublic.model_validate(plan)
        return result
