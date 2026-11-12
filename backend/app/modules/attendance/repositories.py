from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.attendance.models import CheckIn, CheckInRequest


class AttendanceRepository:
    def __init__(self, session: Session):
        self.session = session

    def request(self, key: str):
        return self.session.get(CheckInRequest, key)

    def on_day(self, student_id: str, day: date):
        return self.session.scalar(
            select(CheckIn).where(CheckIn.student_id == student_id, CheckIn.local_day == day)
        )

    def list(self, student_id: str, offset: int, limit: int):
        return self.session.scalars(
            select(CheckIn)
            .where(CheckIn.student_id == student_id)
            .order_by(CheckIn.occurred_at.desc(), CheckIn.id)
            .offset(offset)
            .limit(limit)
        ).all()

    def summary(self, student_id: str):
        latest, total = self.session.execute(
            select(func.max(CheckIn.occurred_at), func.count(CheckIn.id)).where(
                CheckIn.student_id == student_id
            )
        ).one()
        return {"student_id": student_id, "last_visit": latest, "total_visits": total}
