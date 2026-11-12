from datetime import datetime

from app.core.domain import Cents, Input, Name, Output


class PlanCreate(Input):
    name: Name
    monthly_amount_cents: Cents


class PlanPublic(Output):
    id: str
    name: str
    monthly_amount_cents: int
    is_active: bool
    created_at: datetime
