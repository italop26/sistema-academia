from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from celery.exceptions import Retry
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_attendance import suspend, visit
from test_business import business_client as business_client
from test_business import business_db as business_db
from test_business import create_records

from app.core.config import get_settings
from app.modules.absence.models import AbsenceDetection, AbsenceScanRun, AbsenceScanState
from app.modules.absence.repositories import RULE_KEY
from app.modules.absence.services import reserve_scan, scan_absence
from app.modules.absence.tasks import identify_absence
from app.modules.enrollments.models import Enrollment


@pytest.fixture
def absence_clock(business_db, monkeypatch):
    class Clock:
        now = datetime(2028, 2, 1, 12, tzinfo=UTC)

    clock = Clock()
    monkeypatch.setenv("ABSENCE_TRACKING_ENABLED", "true")
    monkeypatch.setattr("app.modules.absence.services.utcnow", lambda: clock.now)
    monkeypatch.setattr("app.modules.attendance.services.utcnow", lambda: clock.now)
    monkeypatch.setattr("app.modules.enrollments.services.utcnow", lambda: clock.now)
    monkeypatch.setattr("app.modules.absence.followups.utcnow", lambda: clock.now)
    get_settings.cache_clear()
    yield clock
    get_settings.cache_clear()


def count(engine):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(AbsenceDetection))


def test_disabled_scan_writes_nothing(business_db, monkeypatch):
    monkeypatch.setenv("ABSENCE_TRACKING_ENABLED", "false")
    get_settings.cache_clear()
    assert scan_absence(business_db)["enabled"] is False
    with Session(business_db) as session:
        assert session.get(AbsenceScanState, RULE_KEY) is None


def test_no_check_in_gets_full_grace_and_one_detection(business_client, business_db, absence_clock):
    create_records(business_client)
    assert scan_absence(business_db)["detected"] == 0
    absence_clock.now += timedelta(hours=240) - timedelta(microseconds=1)
    assert scan_absence(business_db)["detected"] == 0
    absence_clock.now += timedelta(microseconds=1)
    assert scan_absence(business_db)["detected"] == 1
    assert scan_absence(business_db)["detected"] == 0
    assert count(business_db) == 1


def test_last_visit_restarts_240_hours(business_client, business_db, absence_clock):
    student, _, enrollment = create_records(business_client)
    scan_absence(business_db)
    absence_clock.now += timedelta(days=1)
    assert visit(business_client, student, enrollment).status_code == 200
    absence_clock.now += timedelta(hours=240) - timedelta(seconds=1)
    assert scan_absence(business_db)["detected"] == 0
    absence_clock.now += timedelta(seconds=1)
    assert scan_absence(business_db)["detected"] == 1
    assert visit(business_client, student, enrollment).status_code == 200
    assert scan_absence(business_db)["detected"] == 0
    absence_clock.now += timedelta(hours=240)
    assert scan_absence(business_db)["detected"] == 1
    assert count(business_db) == 2


@pytest.mark.parametrize("state", ["inactive", "cancelled", "future", "expired", "suspended"])
def test_ineligible_students_do_not_generate_detection(
    business_client, business_db, absence_clock, state
):
    student, _, enrollment = create_records(
        business_client,
        starts_on="2028-03-01" if state == "future" else "2028-01-01",
        ends_on="2028-02-05" if state == "expired" else None,
    )
    scan_absence(business_db)
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
    absence_clock.now += timedelta(hours=240)
    assert scan_absence(business_db)["detected"] == 0


def test_resume_starts_new_grace(business_client, business_db, absence_clock):
    _, _, enrollment = create_records(business_client)
    scan_absence(business_db)
    absence_clock.now += timedelta(days=8)
    period = suspend(business_client, enrollment).json()
    absence_clock.now += timedelta(days=4)
    assert scan_absence(business_db)["detected"] == 0
    response = business_client.post(
        f"/admin/enrollments/{enrollment['id']}/suspensions/{period['id']}/resume",
        json={"reason": "Retorno"},
    )
    assert response.status_code == 200
    absence_clock.now += timedelta(hours=240) - timedelta(seconds=1)
    assert scan_absence(business_db)["detected"] == 0
    absence_clock.now += timedelta(seconds=1)
    assert scan_absence(business_db)["detected"] == 1


def test_one_available_enrollment_keeps_eligibility(business_client, business_db, absence_clock):
    student, _, enrollment = create_records(business_client)
    other_plan = business_client.post(
        "/admin/plans", json={"name": "Segundo plano", "monthly_amount_cents": 1000}
    ).json()
    business_client.post(
        "/admin/enrollments",
        json={
            "student_id": student["id"],
            "plan_id": other_plan["id"],
            "starts_on": "2028-01-01",
            "due_day": 1,
        },
    )
    scan_absence(business_db)
    absence_clock.now += timedelta(days=8)
    suspend(business_client, enrollment)
    absence_clock.now += timedelta(days=2)
    assert scan_absence(business_db)["detected"] == 1
    assert count(business_db) == 1


def test_eligibility_gap_resets_grace(business_client, business_db, absence_clock):
    student, plan, enrollment = create_records(business_client, ends_on="2028-02-03")
    scan_absence(business_db)
    absence_clock.now += timedelta(days=5)
    business_client.post(
        f"/admin/enrollments/{enrollment['id']}/cancel", json={"reason": "Renovação"}
    )
    renewed = business_client.post(
        "/admin/enrollments",
        json={
            "student_id": student["id"],
            "plan_id": plan["id"],
            "starts_on": "2028-02-06",
            "due_day": 1,
        },
    ).json()
    with Session(business_db) as session, session.begin():
        session.get(Enrollment, renewed["id"]).created_at = absence_clock.now
    absence_clock.now += timedelta(days=5)
    assert scan_absence(business_db)["detected"] == 0
    absence_clock.now += timedelta(days=5)
    assert scan_absence(business_db)["detected"] == 1


def test_batch_cursor_eventually_reaches_all_students(
    business_client, business_db, absence_clock, monkeypatch
):
    for index in range(5):
        create_records(business_client, name=f"Aluno {index}")
    scan_absence(business_db)
    monkeypatch.setenv("ABSENCE_BATCH_SIZE", "2")
    get_settings.cache_clear()
    absence_clock.now += timedelta(days=10)
    results = [scan_absence(business_db) for _ in range(3)]
    assert [row["processed"] for row in results] == [2, 2, 1]
    assert count(business_db) == 5
    assert scan_absence(business_db)["detected"] == 0


def test_parallel_scans_and_restart_do_not_duplicate(business_client, business_db, absence_clock):
    create_records(business_client)
    scan_absence(business_db)
    absence_clock.now += timedelta(days=10)
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: scan_absence(business_db), range(10)))
    assert count(business_db) == 1
    get_settings.cache_clear()
    assert scan_absence(business_db)["detected"] == 0


def test_audit_failure_rolls_back_and_recovers_from_cursor(
    business_client, business_db, absence_clock, monkeypatch
):
    create_records(business_client)
    scan_absence(business_db)
    absence_clock.now += timedelta(days=10)

    def fail(*args, **kwargs):
        raise RuntimeError("private-content-not-for-history")

    with monkeypatch.context() as patch:
        patch.setattr("app.modules.absence.services.record_event", fail)
        with pytest.raises(RuntimeError):
            scan_absence(business_db)
    assert count(business_db) == 0
    with Session(business_db) as session:
        state = session.get(AbsenceScanState, RULE_KEY)
        assert state.cursor == "" and state.last_error_code == "RuntimeError"
        assert state.consecutive_failures == 1 and state.lease_token is None
    assert scan_absence(business_db).get("busy") is True
    absence_clock.now += timedelta(seconds=60)
    assert scan_absence(business_db)["detected"] == 1


def test_crashed_scan_lease_expires_and_history_is_preserved(
    business_client, business_db, absence_clock
):
    create_records(business_client)
    scan_absence(business_db)
    absence_clock.now += timedelta(days=10)
    old_token, _ = reserve_scan(business_db)
    assert scan_absence(business_db).get("busy") is True
    absence_clock.now += timedelta(seconds=121)
    assert scan_absence(business_db)["detected"] == 1
    with Session(business_db) as session:
        assert session.get(AbsenceScanRun, old_token).status == "interrupted"


def test_celery_retry_is_bounded_and_does_not_serialize_error(monkeypatch):
    def fail():
        raise OperationalError("SELECT", {}, RuntimeError("private-database-details"))

    calls = []

    def retry(**kwargs):
        calls.append(kwargs)
        raise Retry()

    monkeypatch.setattr("app.modules.absence.tasks.scan_absence", fail)
    monkeypatch.setattr(identify_absence, "retry", retry)
    identify_absence.push_request(retries=0)
    try:
        with pytest.raises(Retry):
            identify_absence.run()
    finally:
        identify_absence.pop_request()
    assert calls == [{"countdown": 60}]
    identify_absence.push_request(retries=3)
    try:
        with pytest.raises(OperationalError):
            identify_absence.run()
    finally:
        identify_absence.pop_request()
    assert len(calls) == 1


def test_migration_matches_metadata_and_protects_activation(business_db, absence_clock):
    command.check(Config("alembic.ini"))
    scan_absence(business_db)
    with pytest.raises(RuntimeError, match="Downgrade bloqueado"):
        command.downgrade(Config("alembic.ini"), "20261112_01")


def test_last_supported_end_date_does_not_overflow(business_client, business_db, absence_clock):
    create_records(business_client, ends_on="9999-12-31")
    scan_absence(business_db)
    absence_clock.now += timedelta(days=10)
    assert scan_absence(business_db)["detected"] == 1
