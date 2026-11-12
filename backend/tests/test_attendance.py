from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_business import ADMIN_ID, MEMBER_ID, create_records, generate
from test_business import business_client as business_client
from test_business import business_db as business_db

from app.core.security import create_access_token
from app.modules.attendance.models import CheckIn, CheckInRequest
from app.modules.attendance.repositories import AttendanceRepository
from app.modules.attendance.schemas import CheckInCreate
from app.modules.attendance.services import AttendanceService
from app.modules.audit.models import AuditEvent


@pytest.fixture
def attendance_clock(monkeypatch):
    class Clock:
        now = datetime(2028, 2, 10, 12, tzinfo=UTC)

    clock = Clock()
    monkeypatch.setattr("app.modules.attendance.services.utcnow", lambda: clock.now)
    monkeypatch.setattr("app.modules.enrollments.services.utcnow", lambda: clock.now)
    return clock


def body(student, enrollment, key=None):
    return {
        "student_id": student["id"],
        "enrollment_id": enrollment["id"],
        "idempotency_key": key or str(uuid4()),
    }


def visit(client, student, enrollment, key=None):
    return client.post("/admin/attendance/check-ins", json=body(student, enrollment, key))


def suspend(client, enrollment, key=None):
    return client.post(
        f"/admin/enrollments/{enrollment['id']}/suspend",
        json={
            "request_key": key or str(uuid4()),
            "reason": "Pausa solicitada pelo aluno",
        },
    )


def test_daily_check_in_history_summary_and_persistent_keys(
    business_client, business_db, attendance_clock
):
    student, _, enrollment = create_records(business_client)
    path = f"/admin/attendance/students/{student['id']}"
    assert business_client.get(path).json()["last_visit"] is None
    first_key, second_key = str(uuid4()), str(uuid4())
    first = visit(business_client, student, enrollment, first_key)
    assert first.status_code == 200
    assert first.json()["local_day"] == "2028-02-10"
    assert visit(business_client, student, enrollment, second_key).json() == first.json()
    attendance_clock.now += timedelta(days=1)
    assert visit(business_client, student, enrollment, second_key).json() == first.json()
    second = visit(business_client, student, enrollment)
    assert second.json()["id"] != first.json()["id"]
    summary = business_client.get(path).json()
    assert summary["total_visits"] == 2 and summary["last_visit"] == second.json()["occurred_at"]
    assert business_client.get(path + "/check-ins?limit=1").json() == [second.json()]
    assert business_client.get(path + "/check-ins?limit=1&offset=1").json() == [first.json()]
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(CheckInRequest)) == 3
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_type == "check_in")
            )
            == 2
        )


def test_day_boundary_uses_fortaleza(business_client, attendance_clock):
    student, _, enrollment = create_records(business_client)
    attendance_clock.now = datetime(2028, 2, 10, 2, 59, 59, tzinfo=UTC)
    first = visit(business_client, student, enrollment).json()
    attendance_clock.now += timedelta(seconds=1)
    second = visit(business_client, student, enrollment).json()
    assert first["local_day"] == "2028-02-09"
    assert second["local_day"] == "2028-02-10" and first["id"] != second["id"]


@pytest.mark.parametrize(
    "state", ["inactive", "cancelled", "future", "expired", "suspended", "other_student"]
)
def test_ineligible_check_in_is_rejected(business_client, attendance_clock, state):
    student, _, enrollment = create_records(
        business_client,
        starts_on="2028-03-01" if state == "future" else "2028-01-01",
        ends_on="2028-02-09" if state == "expired" else None,
    )
    if state == "inactive":
        business_client.post(
            f"/admin/students/{student['id']}/deactivate", json={"reason": "Inativo"}
        )
    elif state == "cancelled":
        business_client.post(
            f"/admin/enrollments/{enrollment['id']}/cancel", json={"reason": "Cancelado"}
        )
    elif state == "suspended":
        assert suspend(business_client, enrollment).status_code == 200
    elif state == "other_student":
        student = business_client.post("/admin/students", json={"name": "Outro aluno"}).json()
    assert visit(business_client, student, enrollment).status_code == 409


def test_idempotency_key_cannot_move_to_another_student(business_client, attendance_clock):
    student, _, enrollment = create_records(business_client)
    key = str(uuid4())
    assert visit(business_client, student, enrollment, key).status_code == 200
    other_student, _, other_enrollment = create_records(business_client, name="Outro")
    assert visit(business_client, other_student, other_enrollment, key).status_code == 409


def test_two_enrollments_keep_one_daily_visit(business_client, attendance_clock):
    student, _, enrollment = create_records(business_client)
    plan = business_client.post(
        "/admin/plans", json={"name": "Outro plano", "monthly_amount_cents": 1000}
    ).json()
    other = business_client.post(
        "/admin/enrollments",
        json={
            "student_id": student["id"],
            "plan_id": plan["id"],
            "starts_on": "2028-01-01",
            "due_day": 1,
        },
    ).json()
    first = visit(business_client, student, enrollment)
    assert visit(business_client, student, other).json() == first.json()


def test_suspend_resume_is_audited_and_keeps_financial_rules(business_client, attendance_clock):
    student, _, enrollment = create_records(business_client)
    key = str(uuid4())
    period = suspend(business_client, enrollment, key)
    assert period.status_code == 200
    assert suspend(business_client, enrollment, key).json() == period.json()
    assert suspend(business_client, enrollment).status_code == 409
    fee = generate(business_client, enrollment["id"]).json()
    assert (
        business_client.post(
            f"/admin/monthly-fees/{fee['id']}/pay",
            json={
                "amount_cents": fee["amount_cents"],
                "note": "Pagamento durante suspensão",
            },
        ).status_code
        == 200
    )
    assert visit(business_client, student, enrollment).status_code == 409
    attendance_clock.now += timedelta(hours=1)
    path = f"/admin/enrollments/{enrollment['id']}/suspensions/{period.json()['id']}/resume"
    resumed = business_client.post(path, json={"reason": "Retorno do aluno"})
    assert resumed.status_code == 200 and resumed.json()["ends_at"] is not None
    assert business_client.post(path, json={"reason": "Repetição segura"}).json() == resumed.json()
    assert visit(business_client, student, enrollment).status_code == 200
    # Repeating an old resume must never end a later suspension.
    assert suspend(business_client, enrollment).status_code == 200
    assert business_client.post(path, json={"reason": "Repetição antiga"}).status_code == 200
    assert visit(business_client, student, enrollment).status_code == 409
    events = business_client.get(
        f"/admin/history?entity_type=enrollment&entity_id={enrollment['id']}"
    ).json()
    assert [event["action"] for event in events].count("resumed") == 1


def test_failed_history_rolls_back_check_in_and_request(
    business_client, business_db, attendance_clock, monkeypatch
):
    student, _, enrollment = create_records(business_client)

    def fail(*args, **kwargs):
        raise RuntimeError("controlled-audit-failure")

    monkeypatch.setattr("app.modules.attendance.services.record_event", fail)
    assert visit(business_client, student, enrollment).status_code == 500
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(CheckIn)) == 0
        assert session.scalar(select(func.count()).select_from(CheckInRequest)) == 0


def test_parallel_requests_have_one_visit(business_client, business_db, attendance_clock):
    student, _, enrollment = create_records(business_client)

    def check(_):
        with Session(business_db, expire_on_commit=False) as session:
            return (
                AttendanceService(AttendanceRepository(session))
                .check_in(
                    CheckInCreate(**body(student, enrollment)),
                    ADMIN_ID,
                )
                .id
            )

    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(check, range(12)))
    assert len(set(ids)) == 1
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(CheckInRequest)) == 12


@pytest.mark.parametrize("role,status", [(None, 401), (MEMBER_ID, 403)])
def test_attendance_and_suspension_require_admin(business_client, attendance_clock, role, status):
    student, _, enrollment = create_records(business_client)
    business_client.headers.pop("Authorization")
    if role:
        business_client.headers["Authorization"] = f"Bearer {create_access_token(role)[0]}"
    assert visit(business_client, student, enrollment).status_code == status
    assert business_client.get(f"/admin/attendance/students/{student['id']}").status_code == status
    assert (
        business_client.get(f"/admin/attendance/students/{student['id']}/check-ins").status_code
        == status
    )
    assert suspend(business_client, enrollment).status_code == status
    assert (
        business_client.get(f"/admin/enrollments/{enrollment['id']}/suspensions").status_code
        == status
    )
    assert (
        business_client.post(
            f"/admin/enrollments/{enrollment['id']}/suspensions/{uuid4()}/resume",
            json={"reason": "Sem acesso"},
        ).status_code
        == status
    )


def test_schema_matches_and_history_blocks_downgrade(
    business_client, business_db, attendance_clock
):
    command.check(Config("alembic.ini"))
    student, _, enrollment = create_records(business_client)
    result = visit(business_client, student, enrollment).json()
    with Session(business_db) as session, pytest.raises(IntegrityError):
        session.add(
            CheckIn(
                student_id=student["id"],
                enrollment_id=enrollment["id"],
                actor_id=ADMIN_ID,
                occurred_at=attendance_clock.now,
                local_day=datetime.fromisoformat(result["local_day"]).date(),
            )
        )
        session.commit()
    with pytest.raises(RuntimeError, match="Downgrade bloqueado"):
        command.downgrade(Config("alembic.ini"), "20261110_05")


def test_client_cannot_supply_timestamp(business_client, attendance_clock):
    student, _, enrollment = create_records(business_client)
    assert (
        business_client.post(
            "/admin/attendance/check-ins",
            json={
                **body(student, enrollment),
                "occurred_at": "2020-01-01T12:00:00Z",
            },
        ).status_code
        == 422
    )
