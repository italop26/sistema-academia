from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.students.models import Student


class StudentRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, student_id: str, lock: bool = False):
        query = select(Student).where(Student.id == student_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def list(self, offset: int, limit: int):
        return self.session.scalars(
            select(Student).order_by(Student.created_at, Student.id).offset(offset).limit(limit)
        ).all()

    def add(self, student: Student):
        self.session.add(student)
        self.session.flush()
