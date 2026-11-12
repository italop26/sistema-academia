from app.core.database import write_transaction
from app.core.domain import required
from app.modules.audit.repositories import record_event
from app.modules.students.models import Student
from app.modules.students.repositories import StudentRepository
from app.modules.students.schemas import Deactivate, StudentCreate, StudentPublic
from app.modules.users.repositories import UserRepository


class StudentService:
    def __init__(self, repository: StudentRepository):
        self.repository = repository

    def create(self, data: StudentCreate, actor_id: str) -> StudentPublic:
        with write_transaction(self.repository.session):
            if data.user_id:
                required(
                    UserRepository(self.repository.session).get_by_id(str(data.user_id)), "Conta"
                )
            student = Student(
                name=data.name,
                email=str(data.email) if data.email else None,
                user_id=str(data.user_id) if data.user_id else None,
            )
            self.repository.add(student)
            result = StudentPublic.model_validate(student)
            record_event(
                self.repository.session,
                "student",
                student.id,
                "created",
                actor_id,
                result.model_dump(mode="json"),
            )
        return result

    def deactivate(self, student_id: str, data: Deactivate, actor_id: str):
        with write_transaction(self.repository.session):
            student = required(self.repository.get(student_id, lock=True), "Aluno")
            before = StudentPublic.model_validate(student).model_dump(mode="json")
            if student.is_active:
                student.is_active = False
                record_event(
                    self.repository.session,
                    "student",
                    student.id,
                    "deactivated",
                    actor_id,
                    {**before, "is_active": False},
                    before,
                    data.reason,
                )
            result = StudentPublic.model_validate(student)
        return result
