from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_business import MEMBER_ID, create_records, generate
from test_business import business_client as business_client
from test_business import business_db as business_db

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.modules.billing.models import MonthlyFee
from app.modules.notifications.models import Reminder, ReminderAttempt
from app.modules.notifications.repositories import NotificationRepository
from app.modules.notifications.schemas import ReminderPublic
from app.modules.notifications.services import NotificationService, dispatch_pending, scan_overdue


class Clock:
    now = datetime(2028, 3, 1, 12, tzinfo=UTC)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class FailedSender:
    def send(self, _data):
        raise RuntimeError("sensitive-sender-data")


@pytest.mark.parametrize(
    "instant,expected",
    [
        (datetime(2028, 3, 1, 2, 59, 59, tzinfo=UTC), date(2028, 2, 29)),
        (datetime(2028, 3, 1, 3, 0, 0, tzinfo=UTC), date(2028, 3, 1)),
    ],
)
def test_local_day_changes_at_fortaleza_midnight(monkeypatch, instant, expected):
    from app.core import domain

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(domain, "datetime", FrozenDatetime)
    assert domain.local_today() == expected


@pytest.fixture
def notification_clock(business_db, monkeypatch):
    clock = Clock()
    monkeypatch.setenv("FINANCIAL_AUTOMATION_ENABLED", "true")
    monkeypatch.setattr("app.modules.notifications.services.local_today", lambda: date(2028, 3, 1))
    monkeypatch.setattr("app.modules.billing.presenters.local_today", lambda: date(2028, 3, 1))
    monkeypatch.setattr("app.modules.notifications.services.utcnow", lambda: clock.now)
    get_settings.cache_clear()
    yield clock
    get_settings.cache_clear()


def make_fee(client):
    _, _, enrollment = create_records(client)
    return generate(client, enrollment["id"]).json()


def plan_one(client, engine):
    fee = make_fee(client)
    assert scan_overdue(engine)["created"] == 1
    with Session(engine) as session:
        reminder_id = session.scalar(
            select(Reminder.id).where(Reminder.monthly_fee_id == fee["id"])
        )
    return fee, reminder_id


def reserve(engine, reminder_id):
    with Session(engine, expire_on_commit=False) as session:
        return NotificationService(NotificationRepository(session)).reserve(reminder_id)


def deliver(engine, reminder_id, token, sender=None):
    with Session(engine, expire_on_commit=False) as session:
        return NotificationService(NotificationRepository(session)).deliver(
            reminder_id, token, sender
        )


def current(engine, reminder_id):
    with Session(engine) as session:
        return ReminderPublic.model_validate(session.get(Reminder, reminder_id))


def count(engine, model):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def test_disabled_automation_is_noop(business_client, business_db, monkeypatch):
    make_fee(business_client)
    monkeypatch.setenv("FINANCIAL_AUTOMATION_ENABLED", "false")
    get_settings.cache_clear()
    assert scan_overdue(business_db)["enabled"] is False
    assert dispatch_pending(business_db)["enabled"] is False
    assert count(business_db, Reminder) == 0


def test_scan_is_idempotent_and_keeps_status_derived(
    business_client, business_db, notification_clock
):
    fee, reminder_id = plan_one(business_client, business_db)
    assert scan_overdue(business_db)["created"] == 0
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == "pendente"
    assert current(business_db, reminder_id).status == "pending"
    assert count(business_db, Reminder) == 1


@pytest.mark.parametrize("state", ["paid", "cancelled", "due_today", "future"])
def test_scan_skips_ineligible_fees(business_client, business_db, notification_clock, state):
    fee = make_fee(business_client)
    if state == "paid":
        business_client.post(
            f"/admin/monthly-fees/{fee['id']}/pay",
            json={
                "amount_cents": fee["amount_cents"],
                "note": "Quitado antes da varredura",
            },
        )
    elif state == "cancelled":
        business_client.post(
            f"/admin/monthly-fees/{fee['id']}/cancel",
            json={"reason": "Cancelado antes da varredura"},
        )
    else:
        with Session(business_db) as session, session.begin():
            session.get(MonthlyFee, fee["id"]).due_on = date(
                2028, 3, 1 if state == "due_today" else 2
            )
    assert scan_overdue(business_db)["created"] == 0


@pytest.mark.parametrize("action,why", [("pay", "paid"), ("cancel", "cancelled")])
def test_payment_or_cancellation_before_send_suppresses(
    business_client,
    business_db,
    notification_clock,
    action,
    why,
):
    fee, reminder_id = plan_one(business_client, business_db)
    token = reserve(business_db, reminder_id)
    body = (
        {"amount_cents": fee["amount_cents"], "note": "Quitação anterior ao envio"}
        if action == "pay"
        else {
            "reason": "Cancelamento anterior ao envio",
        }
    )
    assert (
        business_client.post(f"/admin/monthly-fees/{fee['id']}/{action}", json=body).status_code
        == 200
    )
    sender = Mock()
    assert deliver(business_db, reminder_id, token, sender) == "suppressed"
    sender.send.assert_not_called()
    row = current(business_db, reminder_id)
    assert row.suppression_reason == why and row.attempt_count == 0 and row.receipt is None
    assert count(business_db, ReminderAttempt) == 0


def test_repeated_delivery_has_one_local_receipt(business_client, business_db, notification_clock):
    _, reminder_id = plan_one(business_client, business_db)
    token = reserve(business_db, reminder_id)
    assert deliver(business_db, reminder_id, token) == "sent"
    assert deliver(business_db, reminder_id, token) == "stale"
    row = current(business_db, reminder_id)
    assert row.attempt_count == 1 and "NENHUMA MENSAGEM REAL" in row.message
    assert row.receipt.startswith("TEST-REMINDER-")
    assert count(business_db, ReminderAttempt) == 1
    assert scan_overdue(business_db)["created"] == 0


def test_broker_failure_preserves_outbox_without_consuming_send_attempts(
    business_client,
    business_db,
    notification_clock,
):
    _, reminder_id = plan_one(business_client, business_db)

    def fail(_id, _token):
        raise ConnectionError("sensitive-redis-info")

    assert dispatch_pending(business_db, fail)["failed"] == 1
    row = current(business_db, reminder_id)
    assert row.publication_failures == 1 and row.attempt_count == 0 and row.lease_until is None
    captured = []

    def publisher(rid, token):
        captured.append((rid, token))

    assert dispatch_pending(business_db, publisher)["published"] == 0
    notification_clock.advance(60)
    assert dispatch_pending(business_db, publisher)["published"] == 1
    assert deliver(business_db, *captured[0]) == "sent"


def test_expired_reservation_recovers_and_old_task_is_ignored(
    business_client,
    business_db,
    notification_clock,
):
    _, reminder_id = plan_one(business_client, business_db)
    old = reserve(business_db, reminder_id)
    assert reserve(business_db, reminder_id) is None
    notification_clock.advance(121)
    new = reserve(business_db, reminder_id)
    assert new and new != old
    assert deliver(business_db, reminder_id, old) == "stale"
    assert deliver(business_db, reminder_id, new) == "sent"
    assert count(business_db, ReminderAttempt) == 1


def exhaust(engine, reminder_id, clock):
    for index, delay in enumerate([60, 300, 0]):
        token = reserve(engine, reminder_id)
        assert token
        status = deliver(engine, reminder_id, token, FailedSender())
        assert status == ("retry_wait" if index < 2 else "exhausted")
        assert "sensitive" not in current(engine, reminder_id).model_dump_json()
        if delay:
            assert reserve(engine, reminder_id) is None
            clock.advance(delay)


def test_retry_policy_is_bounded_and_admin_retry_keeps_history(
    business_client,
    business_db,
    notification_clock,
):
    _, reminder_id = plan_one(business_client, business_db)
    exhaust(business_db, reminder_id, notification_clock)
    assert current(business_db, reminder_id).attempt_count == 3
    assert reserve(business_db, reminder_id) is None
    response = business_client.post(
        f"/admin/notifications/reminders/{reminder_id}/retry",
        json={"reason": "Causa de falha resolvida"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["retry_cycles"] == 1
    assert deliver(business_db, reminder_id, reserve(business_db, reminder_id)) == "sent"
    row = current(business_db, reminder_id)
    assert row.attempt_count == 4 and row.cycle_attempts == 1
    attempts = business_client.get(f"/admin/notifications/reminders/{reminder_id}/attempts").json()
    assert [item["outcome"] for item in attempts] == ["failed", "failed", "failed", "sent"]
    assert (
        business_client.post(
            f"/admin/notifications/reminders/{reminder_id}/retry",
            json={"reason": "Não duplicar envio"},
        ).status_code
        == 409
    )


def test_payment_during_retry_wait_prevents_next_send(
    business_client, business_db, notification_clock
):
    fee, reminder_id = plan_one(business_client, business_db)
    assert (
        deliver(business_db, reminder_id, reserve(business_db, reminder_id), FailedSender())
        == "retry_wait"
    )
    assert (
        business_client.post(
            f"/admin/monthly-fees/{fee['id']}/pay",
            json={
                "amount_cents": fee["amount_cents"],
                "note": "Quitado durante o retry",
            },
        ).status_code
        == 200
    )
    notification_clock.advance(60)
    sender = Mock()
    assert (
        deliver(business_db, reminder_id, reserve(business_db, reminder_id), sender) == "suppressed"
    )
    sender.send.assert_not_called()
    assert current(business_db, reminder_id).attempt_count == 1


def test_concurrent_scans_and_deliveries_do_not_duplicate(
    business_client, business_db, notification_clock
):
    make_fee(business_client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: scan_overdue(business_db), range(2)))
    assert count(business_db, Reminder) == 1
    with Session(business_db) as session:
        reminder_id = session.scalar(select(Reminder.id))
    token = reserve(business_db, reminder_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: deliver(business_db, reminder_id, token), range(2)))
    assert sorted(results) == ["sent", "stale"]
    assert count(business_db, ReminderAttempt) == 1


def test_concurrent_dispatchers_publish_once(business_client, business_db, notification_clock):
    plan_one(business_client, business_db)
    captured = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda _: dispatch_pending(
                    business_db, lambda rid, token: captured.append((rid, token))
                ),
                range(2),
            )
        )
    assert len(captured) == 1


def test_batching_does_not_starve_later_fees(
    business_client, business_db, notification_clock, monkeypatch
):
    for _ in range(3):
        make_fee(business_client)
    monkeypatch.setenv("NOTIFICATION_BATCH_SIZE", "1")
    get_settings.cache_clear()
    assert [scan_overdue(business_db)["created"] for _ in range(4)] == [1, 1, 1, 0]


def test_failed_service_does_not_open_implicit_transaction(
    business_client,
    business_db,
    notification_clock,
):
    _, reminder_id = plan_one(business_client, business_db)
    token = reserve(business_db, reminder_id)
    with Session(business_db) as session:
        assert (
            NotificationService(NotificationRepository(session)).deliver(
                reminder_id,
                token,
                FailedSender(),
            )
            == "retry_wait"
        )
        assert not session.in_transaction()


def test_summary_listing_history_and_unique_constraint(
    business_client, business_db, notification_clock
):
    fee, reminder_id = plan_one(business_client, business_db)
    response = business_client.get("/admin/notifications/summary")
    assert response.json()["counts"]["pending"] == 1
    listed = business_client.get("/admin/notifications/reminders").json()
    assert listed[0]["monthly_fee_id"] == fee["id"] and listed[0]["student_name"] == "Aluno A"
    assert (
        business_client.get(
            "/admin/notifications/reminders", params={"student_id": str(uuid4())}
        ).json()
        == []
    )
    with Session(business_db) as session:
        with pytest.raises(IntegrityError), session.begin():
            session.add(Reminder(monthly_fee_id=fee["id"], rule_key="overdue-v1"))
            session.flush()
    events = business_client.get(
        "/admin/history",
        params={
            "entity_type": "reminder",
            "entity_id": reminder_id,
        },
    ).json()
    assert events[0]["action"] == "planned" and events[0]["actor_type"] == "system"


@pytest.mark.parametrize("role,status", [(None, 401), (MEMBER_ID, 403)])
def test_reminder_admin_permissions(business_client, notification_clock, role, status):
    business_client.headers.pop("Authorization")
    if role:
        business_client.headers["Authorization"] = f"Bearer {create_access_token(role)[0]}"
    assert business_client.get("/admin/notifications/summary").status_code == status
    assert business_client.post("/admin/notifications/scan").status_code == status
    assert (
        business_client.post(
            f"/admin/notifications/reminders/{uuid4()}/retry", json={"reason": "Sem permissão"}
        ).status_code
        == status
    )


def test_notification_migration_preserves_schema_and_history(
    business_client, business_db, notification_clock
):
    command.check(Config("alembic.ini"))
    plan_one(business_client, business_db)
    with pytest.raises(RuntimeError, match="Downgrade bloqueado"):
        command.downgrade(Config("alembic.ini"), "20261110_04")
    assert count(business_db, Reminder) == 1


def test_manual_retry_cycles_have_a_hard_limit(business_client, business_db, notification_clock):
    _, reminder_id = plan_one(business_client, business_db)
    for cycle in range(4):
        exhaust(business_db, reminder_id, notification_clock)
        response = business_client.post(
            f"/admin/notifications/reminders/{reminder_id}/retry",
            json={"reason": "Reabertura controlada de teste"},
        )
        assert response.status_code == (200 if cycle < 3 else 409)
    assert current(business_db, reminder_id).attempt_count == 12
    assert count(business_db, ReminderAttempt) == 12


def test_payment_before_admin_retry_dispenses_reminder(
    business_client, business_db, notification_clock
):
    fee, reminder_id = plan_one(business_client, business_db)
    exhaust(business_db, reminder_id, notification_clock)
    business_client.post(
        f"/admin/monthly-fees/{fee['id']}/pay",
        json={
            "amount_cents": fee["amount_cents"],
            "note": "Quitado antes da reabertura",
        },
    )
    response = business_client.post(
        f"/admin/notifications/reminders/{reminder_id}/retry",
        json={"reason": "Rever pendência após quitação"},
    )
    assert response.status_code == 200 and response.json()["status"] == "suppressed"
    assert response.json()["attempt_count"] == 3


def test_history_failure_rolls_back_receipt_and_recovers(
    business_client,
    business_db,
    notification_clock,
    monkeypatch,
):
    from app.modules.notifications.services import record_event as original_record

    _, reminder_id = plan_one(business_client, business_db)

    def fail_success_history(*args, **kwargs):
        if len(args) > 3 and args[3] == "simulated_sent":
            raise RuntimeError("simulated-history-failure")
        return original_record(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr("app.modules.notifications.services.record_event", fail_success_history)
        assert deliver(business_db, reminder_id, reserve(business_db, reminder_id)) == "retry_wait"
    assert current(business_db, reminder_id).receipt is None
    notification_clock.advance(60)
    assert deliver(business_db, reminder_id, reserve(business_db, reminder_id)) == "sent"
    assert count(business_db, ReminderAttempt) == 2


def test_redis_auth_failure_preserves_pending_intent(
    business_client, business_db, notification_clock
):
    _, reminder_id = plan_one(business_client, business_db)
    broken = Mock()
    broken.exists.side_effect = RedisConnectionError("sensitive-redis-info")
    business_client.app.dependency_overrides[get_redis] = lambda: broken
    response = business_client.post("/admin/notifications/scan")
    assert response.status_code == 503 and "sensitive" not in response.text
    assert current(business_db, reminder_id).status == "pending"
