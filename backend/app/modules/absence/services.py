from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_engine, write_transaction
from app.core.domain import utcnow
from app.modules.absence.followups import reconcile
from app.modules.absence.models import AbsenceDetection, AbsenceScanRun, AbsenceScanState
from app.modules.absence.repositories import RULE_KEY, AbsenceRepository
from app.modules.audit.repositories import record_event
from app.modules.students.repositories import StudentRepository

THRESHOLD = timedelta(hours=240)
LEASE_SECONDS = 120
RETRY_DELAYS = (60, 300, 900)
LOCAL_ZONE = ZoneInfo("America/Fortaleza")
INFINITY = datetime.max.replace(tzinfo=UTC)


def as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def midnight(day):
    return datetime.combine(day, time.min, LOCAL_ZONE).astimezone(UTC)


def eligible_since(repository: AbsenceRepository, student_id: str, now):
    """Union historical eligibility intervals; only a gap in ALL enrollments resets grace."""
    periods = repository.suspensions(student_id)
    intervals = []
    for enrollment in repository.enrollments(student_id):
        start = max(midnight(enrollment.starts_on), as_utc(enrollment.created_at))
        end = (
            midnight(enrollment.ends_on + timedelta(days=1))
            if (enrollment.ends_on and enrollment.ends_on < date.max)
            else INFINITY
        )
        if enrollment.status == "cancelada":
            end = min(end, as_utc(enrollment.cancelled_at or enrollment.created_at))
        pieces = [(start, end)] if start < end else []
        for period in periods:
            if period.enrollment_id != enrollment.id:
                continue
            pause, resume = (
                as_utc(period.starts_at),
                as_utc(period.ends_at) if period.ends_at else INFINITY,
            )
            remaining = []
            for left, right in pieces:
                if resume <= left or pause >= right:
                    remaining.append((left, right))
                else:
                    if left < pause:
                        remaining.append((left, pause))
                    if resume < right:
                        remaining.append((resume, right))
            pieces = remaining
        intervals.extend(pieces)
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return next((start for start, end in merged if start <= now < end), None)


def detect_locked(repository: AbsenceRepository, student_id: str, activated_at, now):
    student = StudentRepository(repository.session).get(student_id, lock=True)
    if not student:
        return False
    eligible = eligible_since(repository, student_id, now) if student.is_active else None
    visit = repository.latest_visit(student_id)
    reconcile(repository.session, student_id, eligible, visit, now)
    if eligible is None:
        return False
    baseline = max(as_utc(activated_at), eligible, as_utc(visit.occurred_at) if visit else eligible)
    if now - baseline < THRESHOLD or repository.existing(student_id, baseline):
        return False
    detection = AbsenceDetection(
        student_id=student_id,
        rule_key=RULE_KEY,
        baseline_at=baseline,
        detected_at=now,
        last_check_in_id=visit.id if visit else None,
    )
    repository.session.add(detection)
    repository.session.flush()
    record_event(
        repository.session,
        "absence_detection",
        detection.id,
        "detected",
        None,
        {
            "student_id": student_id,
            "rule_key": RULE_KEY,
            "baseline_at": baseline.isoformat(),
            "detected_at": now.isoformat(),
            "last_check_in_id": detection.last_check_in_id,
        },
    )
    return True


def reserve_scan(engine):
    with Session(engine, expire_on_commit=False) as session, write_transaction(session):
        repository = AbsenceRepository(session)
        state = repository.state()
        now = utcnow()
        if state is None:
            state = AbsenceScanState(rule_key=RULE_KEY, activated_at=now)
            session.add(state)
            session.flush()
        if (state.lease_until and as_utc(state.lease_until) > now) or (
            state.next_attempt_at and as_utc(state.next_attempt_at) > now
        ):
            return None
        if state.lease_token:
            interrupted = session.get(AbsenceScanRun, state.lease_token)
            if interrupted and interrupted.status == "running":
                interrupted.status, interrupted.finished_at = "interrupted", now
                interrupted.error_code = "lease_expired"
        token = str(uuid4())
        state.lease_token, state.lease_until = token, now + timedelta(seconds=LEASE_SECONDS)
        state.next_attempt_at = None
        session.add(AbsenceScanRun(id=token, started_at=now))
        return token, state.cursor


def fail_scan(engine, token, error):
    with Session(engine) as session, write_transaction(session):
        state = AbsenceRepository(session).state()
        if state.lease_token != token:
            return
        run = session.get(AbsenceScanRun, token)
        run.status, run.finished_at, run.error_code = "failed", utcnow(), type(error).__name__
        state.consecutive_failures += 1
        state.last_error_code = type(error).__name__
        state.next_attempt_at = utcnow() + timedelta(
            seconds=RETRY_DELAYS[min(state.consecutive_failures - 1, len(RETRY_DELAYS) - 1)]
        )
        state.lease_token = state.lease_until = None


def scan_absence(engine=None):
    settings = get_settings()
    if not settings.absence_tracking_enabled:
        return {"enabled": False, "processed": 0, "detected": 0}
    engine = engine or get_engine()
    reservation = reserve_scan(engine)
    if not reservation:
        return {"enabled": True, "busy": True, "processed": 0, "detected": 0}
    token, cursor = reservation
    try:
        with Session(engine) as session:
            ids = AbsenceRepository(session).students_after(cursor, settings.absence_batch_size)
        for student_id in ids:
            with Session(engine) as session, write_transaction(session):
                repository = AbsenceRepository(session)
                state = repository.state()
                now = utcnow()
                if state.lease_token != token or as_utc(state.lease_until) <= now:
                    return {"enabled": True, "stale": True, "processed": 0, "detected": 0}
                detected = detect_locked(repository, student_id, state.activated_at, now)
                run = session.get(AbsenceScanRun, token)
                run.processed += 1
                run.detected += int(detected)
                state.cursor = student_id
        with Session(engine) as session, write_transaction(session):
            state = AbsenceRepository(session).state()
            if state.lease_token != token:
                return {"enabled": True, "stale": True, "processed": 0, "detected": 0}
            if len(ids) < settings.absence_batch_size:
                state.cursor = ""
            state.last_success_at = utcnow()
            state.consecutive_failures, state.last_error_code = 0, None
            state.lease_token = state.lease_until = state.next_attempt_at = None
            run = session.get(AbsenceScanRun, token)
            run.status, run.finished_at = "completed", utcnow()
            result = {"enabled": True, "processed": run.processed, "detected": run.detected}
        return result
    except Exception as error:
        fail_scan(engine, token, error)
        raise
