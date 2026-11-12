"""Real Redis/worker probes. All mutations are guarded to the disposable validation database."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from notification_test_worker import guard
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import get_engine
from app.core.domain import local_today, utcnow
from app.modules.billing.repositories import BillingRepository
from app.modules.billing.schemas import GenerateFee
from app.modules.billing.services import BillingService
from app.modules.enrollments.repositories import EnrollmentRepository
from app.modules.enrollments.schemas import EnrollmentCreate
from app.modules.enrollments.services import EnrollmentService
from app.modules.notifications.models import Reminder, ReminderAttempt
from app.modules.notifications.repositories import NotificationRepository
from app.modules.notifications.services import NotificationService, dispatch_pending, scan_overdue
from app.modules.notifications.tasks import deliver_reminder
from app.modules.plans.repositories import PlanRepository
from app.modules.plans.schemas import PlanCreate
from app.modules.plans.services import PlanService
from app.modules.students.repositories import StudentRepository
from app.modules.students.schemas import StudentCreate
from app.modules.students.services import StudentService
from app.modules.users.models import User, UserRole

ROOT = Path("/app/data")
STATE = ROOT / "notification-runtime.json"
EVIDENCE = ROOT / "notification-runtime-evidence.json"


def wait_for(check, seconds=35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError("Condição operacional não foi alcançada no prazo do teste.")


def record(name, **details):
    evidence = json.loads(EVIDENCE.read_text()) if EVIDENCE.exists() else {}
    evidence[name] = {"passed": True, "at_utc": utcnow().isoformat(), **details}
    EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf8")
    print(f"PASSOU: {name}", flush=True)


def call(service, repository, method, *args):
    with Session(get_engine(), expire_on_commit=False) as session:
        return getattr(service(repository(session)), method)(*args)


def make_fee():
    with Session(get_engine()) as session:
        actor = session.scalar(select(User.id).where(User.role == UserRole.ADMIN))
    assert actor
    student = call(
        StudentService,
        StudentRepository,
        "create",
        StudentCreate(name=f"Runtime automação {uuid4().hex[:8]}"),
        actor,
    )
    plan = call(
        PlanService,
        PlanRepository,
        "create",
        PlanCreate(name="Plano operacional descartável", monthly_amount_cents=15990),
        actor,
    )
    previous = (local_today().replace(day=1) - timedelta(days=1)).replace(day=1)
    enrollment = call(
        EnrollmentService,
        EnrollmentRepository,
        "create",
        EnrollmentCreate(
            student_id=student.id,
            plan_id=plan.id,
            starts_on=previous,
            due_day=1,
        ),
        actor,
    )
    fee = call(
        BillingService,
        BillingRepository,
        "generate",
        GenerateFee(
            enrollment_id=enrollment.id,
            competence=previous.isoformat()[:7],
        ),
        actor,
    )
    return fee.id


def reminder_for(fee_id):
    with Session(get_engine()) as session:
        return session.scalar(select(Reminder.id).where(Reminder.monthly_fee_id == fee_id))


def is_sent(reminder_id):
    with Session(get_engine()) as session:
        row = session.get(Reminder, reminder_id)
        return bool(row and row.status == "sent")


def verify_one(reminder_id):
    with Session(get_engine()) as session:
        row = session.get(Reminder, reminder_id)
        assert row.status == "sent" and row.attempt_count == 1
        assert row.receipt == f"TEST-REMINDER-{row.id}"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReminderAttempt)
                .where(
                    ReminderAttempt.reminder_id == reminder_id,
                )
            )
            == 1
        )


def basic():
    wait_for(lambda: celery_app.control.ping(timeout=1))
    fee_id = make_fee()
    # No manual scan/dispatch: real Beat must identify and publish this fee.
    wait_for(lambda: reminder_for(fee_id))
    reminder_id = reminder_for(fee_id)
    wait_for(lambda: is_sent(reminder_id))
    verify_one(reminder_id)
    record(
        "beat_worker_end_to_end",
        reminder_id=reminder_id,
        test_schedule_seconds=[1, 2],
        production_schedule_seconds=[300, 60],
    )


def load():
    """Bounded SQLite contention probe; run with disposable Beat/worker stopped."""
    started = time.monotonic()
    fee_ids = [make_fee() for _ in range(120)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        # Parallel scans race for the same fees; the database must keep one intention.
        for _ in range(4):
            list(pool.map(lambda _: scan_overdue(), range(8)))
    with Session(get_engine()) as session:
        rows = session.scalars(select(Reminder).where(Reminder.monthly_fee_id.in_(fee_ids))).all()
        assert len(rows) == len(fee_ids)
        reminder_ids = [row.id for row in rows]

    def reserve_one(reminder_id):
        with Session(get_engine(), expire_on_commit=False) as session:
            token = NotificationService(NotificationRepository(session)).reserve(reminder_id)
            assert token
            return reminder_id, token

    work = [reserve_one(reminder_id) for reminder_id in reminder_ids]

    def deliver_one(item):
        with Session(get_engine(), expire_on_commit=False) as session:
            return NotificationService(NotificationRepository(session)).deliver(*item)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(deliver_one, [item for item in work for _ in range(3)]))
    assert results.count("sent") == 120
    assert results.count("stale") == 240
    for reminder_id in reminder_ids:
        verify_one(reminder_id)
    record(
        "sqlite_bounded_load",
        fees=120,
        concurrent_threads=8,
        delivery_calls=360,
        unique_receipts=120,
        stale_duplicates=240,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )


def prepare_redis():
    fee_id = make_fee()
    scan_overdue()
    reminder_id = reminder_for(fee_id)
    assert reminder_id
    STATE.write_text(json.dumps({"redis": reminder_id}), encoding="utf8")
    record("redis_intent_persisted", reminder_id=reminder_id)


def assert_redis_outage():
    reminder_id = json.loads(STATE.read_text())["redis"]
    result = dispatch_pending()
    assert result["failed"] >= 1
    with Session(get_engine()) as session:
        row = session.get(Reminder, reminder_id)
        assert row.status == "pending" and row.attempt_count == 0
        assert row.publication_failures >= 1 and row.lease_until is None
        assert row.last_error_code == "broker_unavailable"
    record("real_redis_outage", no_send_attempt_consumed=True)


def recover_redis():
    wait_for(lambda: celery_app.control.ping(timeout=1))
    reminder_id = json.loads(STATE.read_text())["redis"]
    # Accelerate only the test clock/backoff; leave the production 60-second policy unchanged.
    with Session(get_engine()) as session, session.begin():
        session.get(Reminder, reminder_id).next_attempt_at = utcnow() - timedelta(seconds=1)
    assert dispatch_pending()["published"] >= 1
    wait_for(lambda: is_sent(reminder_id))
    verify_one(reminder_id)
    record("real_redis_recovery", reminder_id=reminder_id, test_backoff_accelerated=True)


def prepare_crash():
    wait_for(lambda: celery_app.control.ping(timeout=1))
    marker = ROOT / "notification-inside-sender"
    marker.unlink(missing_ok=True)
    (ROOT / "notification-pause").write_text("pause", encoding="utf8")
    fee_id = make_fee()
    scan_overdue()
    reminder_id = reminder_for(fee_id)
    state = json.loads(STATE.read_text())
    state["crash"] = reminder_id
    STATE.write_text(json.dumps(state), encoding="utf8")

    def publish(rid, token):
        # Long test-only pause window permits the controller to SIGKILL the container.
        deliver_reminder.apply_async(
            args=[rid, token], retry=False, soft_time_limit=120, time_limit=150
        )

    assert dispatch_pending(publisher=publish)["published"] >= 1
    wait_for(marker.exists)
    record("worker_entered_transaction", reminder_id=reminder_id)


def assert_crash_pending():
    reminder_id = json.loads(STATE.read_text())["crash"]
    with Session(get_engine()) as session:
        row = session.get(Reminder, reminder_id)
        assert row.status == "pending" and row.attempt_count == 0 and row.receipt is None
        assert row.dispatch_token is not None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReminderAttempt)
                .where(
                    ReminderAttempt.reminder_id == reminder_id,
                )
            )
            == 0
        )
    (ROOT / "notification-pause").unlink(missing_ok=True)
    record("worker_sigkill_rollback", no_partial_receipt=True)


def recover_worker():
    wait_for(lambda: celery_app.control.ping(timeout=1))
    reminder_id = json.loads(STATE.read_text())["crash"]
    with Session(get_engine()) as session, session.begin():
        row = session.get(Reminder, reminder_id)
        old_token = row.dispatch_token
        row.lease_until = utcnow() - timedelta(seconds=1)
    assert dispatch_pending()["published"] >= 1
    wait_for(lambda: is_sent(reminder_id))
    deliver_reminder.apply_async(args=[reminder_id, old_token], retry=False)
    time.sleep(1)
    verify_one(reminder_id)
    record(
        "worker_restart_recovered",
        reminder_id=reminder_id,
        stale_token_ignored=True,
        test_lease_accelerated=True,
    )


if __name__ == "__main__":
    guard()
    modes = {
        "basic": basic,
        "load": load,
        "prepare_redis": prepare_redis,
        "assert_redis_outage": assert_redis_outage,
        "recover_redis": recover_redis,
        "prepare_crash": prepare_crash,
        "assert_crash_pending": assert_crash_pending,
        "recover_worker": recover_worker,
    }
    if sys.argv[1] == "report":
        print(EVIDENCE.read_text())
    else:
        modes[sys.argv[1]]()
