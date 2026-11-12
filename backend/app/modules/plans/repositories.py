from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.plans.models import Plan


class PlanRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, plan_id: str, lock: bool = False):
        query = select(Plan).where(Plan.id == plan_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def list(self, offset: int, limit: int):
        return self.session.scalars(
            select(Plan).order_by(Plan.created_at, Plan.id).offset(offset).limit(limit)
        ).all()

    def add(self, plan: Plan):
        self.session.add(plan)
        self.session.flush()
