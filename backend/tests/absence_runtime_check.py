"""Real Beat/worker probe, strictly limited to the disposable validation SQLite."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from notification_runtime_check import call, wait_for
from notification_test_worker import guard
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.core.domain import local_today, utcnow
from app.modules.absence.models import AbsenceDetection, AbsenceScanState
from app.modules.absence.repositories import RULE_KEY
from app.modules.absence.services import as_utc, scan_absence
from app.modules.enrollments.models import Enrollment
from app.modules.enrollments.repositories import EnrollmentRepository
from app.modules.enrollments.schemas import EnrollmentCreate
from app.modules.enrollments.services import EnrollmentService
from app.modules.plans.repositories import PlanRepository
from app.modules.plans.schemas import PlanCreate
from app.modules.plans.services import PlanService
from app.modules.students.repositories import StudentRepository
from app.modules.students.schemas import StudentCreate
from app.modules.students.services import StudentService
from app.modules.users.models import User, UserRole


def main():
    guard()
    with Session(get_engine()) as session:
        actor = session.scalar(select(User.id).where(User.role == UserRole.ADMIN))
    assert actor
    scan_absence()
    cases = []
    for index in range(3):
        name = (
            (f"Ausência{uuid4().hex[:8]}" + "X" * 84)
            if index == 0
            else f"Ausência {uuid4().hex[:8]}"
        )
        student = call(StudentService, StudentRepository, "create", StudentCreate(name=name), actor)
        plan = call(
            PlanService,
            PlanRepository,
            "create",
            PlanCreate(
                name="Plano descartável de frequência",
                monthly_amount_cents=10000,
            ),
            actor,
        )
        enrollment = call(
            EnrollmentService,
            EnrollmentRepository,
            "create",
            EnrollmentCreate(
                student_id=student.id,
                plan_id=plan.id,
                starts_on=local_today() - timedelta(days=20),
                due_day=1,
            ),
            actor,
        )
        with Session(get_engine()) as session, session.begin():
            session.get(Enrollment, enrollment.id).created_at = utcnow() - timedelta(days=20)
        cases.append({"student_id": student.id, "enrollment_id": enrollment.id, "name": name})
    with Session(get_engine()) as session, session.begin():
        state = session.get(AbsenceScanState, RULE_KEY)
        state.activated_at = min(as_utc(state.activated_at), utcnow() - timedelta(days=11))
        state.cursor = ""
    ids = [row["student_id"] for row in cases]

    def detected():
        with Session(get_engine()) as session:
            return (
                len(
                    session.scalars(
                        select(AbsenceDetection).where(
                            AbsenceDetection.student_id.in_(ids),
                            AbsenceDetection.status == "pendente",
                        )
                    ).all()
                )
                == 3
            )

    # No scan after fixture preparation: real Beat and worker must create these detections.
    wait_for(detected, seconds=35)
    root = Path("/app/data")
    (root / "absence-runtime-fixtures.json").write_text(json.dumps(cases), encoding="utf8")
    (root / "absence-runtime-evidence.json").write_text(
        json.dumps(
            {
                "beat_worker_absence": {
                    "passed": True,
                    "at_utc": utcnow().isoformat(),
                    "students": 3,
                    "detections": 3,
                    "test_clock_accelerated": True,
                    "test_schedule_seconds": 1,
                    "normal_schedule_seconds": 300,
                    "threshold_hours": 240,
                },
            },
            indent=2,
        ),
        encoding="utf8",
    )
    print("PASSOU: Beat e worker reais criaram três detecções de ausência no SQLite descartável.")


if __name__ == "__main__":
    main()
