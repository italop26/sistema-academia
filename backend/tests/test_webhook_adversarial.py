import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_business import MEMBER_ID
from test_business import business_client as business_client
from test_business import business_db as business_db
from test_pix_foundation import pix_client as pix_client
from test_webhooks import TEST_SECRET, WEBHOOK_PATH, charge_for, detail, envelope, send
from test_webhooks import webhook_client as webhook_client

from app.core.config import Settings, get_settings
from app.core.errors import ApplicationError
from app.core.security import create_access_token
from app.modules.audit.models import AuditEvent
from app.modules.billing.models import MonthlyFee
from app.modules.payments.models import Charge, Payment
from app.modules.webhooks.models import WebhookEvent


def count(engine, model):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize("offset", [-3600, 3600])
def test_stale_or_future_signature_does_not_persist(webhook_client, business_db, offset):
    _, charge = charge_for(webhook_client)
    response = send(webhook_client, envelope(charge), timestamp=int(time.time()) + offset)
    assert response.status_code == 401
    assert count(business_db, WebhookEvent) == count(business_db, Payment) == 0


@pytest.mark.parametrize("timestamp", ["abc", "-1", "0000000000", "1" * 1000])
def test_malformed_transport_timestamp(webhook_client, business_db, timestamp):
    assert send(webhook_client, {}, timestamp=timestamp).status_code == 401
    assert count(business_db, WebhookEvent) == 0


def test_signed_body_cannot_be_tampered(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    payload = envelope(charge)
    raw = json.dumps(payload).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(
        TEST_SECRET.encode(), stamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    response = webhook_client.post(
        WEBHOOK_PATH,
        content=json.dumps({**payload, "amount_cents": 1}),
        headers={"X-Pix-Test-Timestamp": stamp, "X-Pix-Test-Signature": f"sha256={signature}"},
    )
    assert response.status_code == 401 and count(business_db, WebhookEvent) == 0


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b"null", b'{"x":NaN}', b"\xff"])
def test_malformed_authenticated_body_is_not_saved(webhook_client, business_db, raw):
    assert send(webhook_client, raw=raw).status_code == 422
    assert count(business_db, WebhookEvent) == 0


def test_duplicate_json_keys_and_oversize_are_rejected(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    payload = envelope(charge)
    raw = json.dumps(payload)[:-1] + f',"event_id":"{uuid4()}"' + "}"
    assert send(webhook_client, raw=raw.encode()).status_code == 422
    assert send(webhook_client, raw=b" " * 16385).status_code == 413
    assert count(business_db, WebhookEvent) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_simulated": False},
        {"is_simulated": 1},
        {"schema_version": 2},
        {"schema_version": True},
        {"schema_version": 1.0},
        {"schema_version": "1"},
        {"event_type": "refund.created"},
        {"unexpected_secret": "not-accepted"},
        {"amount_cents": True},
        {"amount_cents": 1.5},
        {"amount_cents": -1},
        {"occurred_at": "2026-11-10T12:00:00"},
        {"external_payment_id": None},
    ],
)
def test_invalid_envelope_does_not_enter_inbox(webhook_client, business_db, overrides):
    _, charge = charge_for(webhook_client)
    assert send(webhook_client, envelope(charge, **overrides)).status_code == 422
    assert count(business_db, WebhookEvent) == 0


@pytest.mark.parametrize(
    "kind,code",
    [
        ("charge", "not_found"),
        ("reference", "invalid_reference"),
        ("amount", "amount_mismatch"),
        ("currency", "amount_mismatch"),
        ("before_creation", "invalid_event_time"),
        ("future", "invalid_event_time"),
    ],
)
def test_authenticated_divergence_is_retained_without_payment(
    webhook_client, business_db, kind, code
):
    fee, charge = charge_for(webhook_client)
    data = envelope(charge)
    if kind == "charge":
        data["charge_id"] = str(uuid4())
    elif kind == "reference":
        data["reference"] = "TEST-PIX-wrong-reference"
    elif kind == "amount":
        data["amount_cents"] = 1
    elif kind == "currency":
        data["currency"] = "USD"
    elif kind == "before_creation":
        data["occurred_at"] = (
            datetime.fromisoformat(charge["created_at"].replace("Z", "+00:00"))
            - timedelta(seconds=1)
        ).isoformat()
    else:
        data["occurred_at"] = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
    response = send(webhook_client, data)
    assert response.status_code == 202
    event = detail(webhook_client, response)
    assert event["status"] == "rejected" and event["last_error_code"] == code
    assert count(business_db, Payment) == 0
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == "pendente"


@pytest.mark.parametrize("after_expiration", [False, True])
def test_delayed_confirmation_does_not_silently_settle_expired_charge(
    webhook_client,
    business_db,
    monkeypatch,
    after_expiration,
):
    _, charge = charge_for(webhook_client)
    expires = datetime.fromisoformat(charge["expires_at"].replace("Z", "+00:00"))
    future = expires + timedelta(seconds=2)
    data = envelope(charge)
    if after_expiration:
        data["occurred_at"] = (expires + timedelta(seconds=1)).isoformat()
    monkeypatch.setattr("app.modules.webhooks.services.utcnow", lambda: future)
    monkeypatch.setattr("app.modules.payments.services.utcnow", lambda: future)
    response = send(webhook_client, data)
    assert response.status_code == 202
    event = detail(webhook_client, response)
    assert event["status"] == "rejected"
    assert event["last_error_code"] == ("late_payment" if after_expiration else "invalid_charge")
    assert count(business_db, WebhookEvent) == 1 and count(business_db, Payment) == 0


@pytest.mark.parametrize(
    "first,second,fee_status,second_status",
    [
        ("payment.confirmed", "charge.pending", "paga", "ignored"),
        ("payment.confirmed", "charge.cancelled", "paga", "ignored"),
        ("charge.cancelled", "charge.pending", "pendente", "ignored"),
        ("charge.cancelled", "payment.confirmed", "pendente", "rejected"),
    ],
)
def test_out_of_order_events_do_not_regress_terminal_states(
    webhook_client,
    business_db,
    first,
    second,
    fee_status,
    second_status,
):
    fee, charge = charge_for(webhook_client)
    assert send(webhook_client, envelope(charge, first)).status_code == 200
    response = send(webhook_client, envelope(charge, second))
    assert response.json()["status"] == second_status
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == fee_status
        assert session.get(Charge, charge["id"]).status == (
            "paid" if fee_status == "paga" else "cancelled"
        )
    assert count(business_db, Payment) == (1 if fee_status == "paga" else 0)


def test_new_event_same_receipt_is_ignored_without_second_settlement(webhook_client, business_db):
    fee, charge = charge_for(webhook_client)
    data = envelope(charge)
    assert send(webhook_client, data).json()["status"] == "processed"
    second = send(webhook_client, {**data, "event_id": str(uuid4())})
    assert second.json()["status"] == "ignored"
    assert detail(webhook_client, second)["result_code"] == "already_applied"
    with Session(business_db) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_id == fee["id"],
                    AuditEvent.action == "paid",
                )
            )
            == 1
        )
    assert count(business_db, Payment) == 1 and count(business_db, WebhookEvent) == 2


def test_external_payment_cannot_be_reused_for_another_student(webhook_client, business_db):
    _, first_charge = charge_for(webhook_client)
    second_fee, second_charge = charge_for(webhook_client)
    first = envelope(first_charge)
    assert send(webhook_client, first).status_code == 200
    second = send(
        webhook_client, envelope(second_charge, external_payment_id=first["external_payment_id"])
    )
    assert detail(webhook_client, second)["last_error_code"] == "payment_conflict"
    with Session(business_db) as session:
        assert session.get(MonthlyFee, second_fee["id"]).status == "pendente"
    assert count(business_db, Payment) == 1


def test_duplicate_delivery_of_failed_event_requires_admin_retry(
    webhook_client, business_db, monkeypatch
):
    _, charge = charge_for(webhook_client)
    data = envelope(charge)

    def fail(*args, **kwargs):
        raise RuntimeError(TEST_SECRET + "-internal-failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.modules.payments.services.record_event", fail)
        first = send(webhook_client, data)
    repeated = send(webhook_client, data)
    event = detail(webhook_client, repeated)
    assert first.json()["id"] == repeated.json()["id"]
    assert event["status"] == "failed" and event["attempt_count"] == 1
    assert event["delivery_count"] == 2 and TEST_SECRET not in json.dumps(event)
    assert count(business_db, Payment) == 0


@pytest.mark.parametrize("same_id", [False, True])
def test_concurrent_deliveries_apply_only_one_payment(webhook_client, business_db, same_id):
    fee, charge = charge_for(webhook_client)
    first = envelope(charge)
    second = dict(first) if same_id else {**first, "event_id": str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda data: send(webhook_client, data), [first, second]))
    assert all(response.status_code == 200 for response in responses)
    assert count(business_db, Payment) == 1
    assert count(business_db, WebhookEvent) == (1 if same_id else 2)
    with Session(business_db) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_id == fee["id"],
                    AuditEvent.action == "paid",
                )
            )
            == 1
        )
        if same_id:
            event = session.scalar(select(WebhookEvent))
            assert event.delivery_count == 2 and event.attempt_count == 1


def test_manual_payment_racing_webhook_has_single_winner(webhook_client, business_db):
    fee, charge = charge_for(webhook_client)
    data = envelope(charge)

    def apply(kind):
        if kind == "pix":
            return send(webhook_client, data)
        return webhook_client.post(
            f"/admin/monthly-fees/{fee['id']}/pay",
            json={
                "amount_cents": fee["amount_cents"],
                "note": "Recebimento manual concorrente",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        manual, webhook = list(executor.map(apply, ["manual", "pix"]))
    assert (manual.status_code, webhook.status_code) in {(200, 202), (409, 200)}
    assert count(business_db, Payment) == 1
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == "paga"


def test_cancelled_monthly_fee_is_not_paid_by_late_webhook(webhook_client, business_db):
    fee, charge = charge_for(webhook_client)
    assert (
        webhook_client.post(
            f"/admin/monthly-fees/{fee['id']}/cancel", json={"reason": "Cancelamento anterior"}
        ).status_code
        == 200
    )
    response = send(webhook_client, envelope(charge))
    assert detail(webhook_client, response)["status"] == "rejected"
    assert count(business_db, Payment) == 0


def test_retry_requires_admin_and_rejects_terminal_events(webhook_client):
    _, charge = charge_for(webhook_client)
    response = send(webhook_client, envelope(charge))
    path = f"/admin/pix/events/{response.json()['id']}/retry"
    assert webhook_client.post(path, json={"reason": "Já concluído"}).status_code == 409
    assert detail(webhook_client, response)["attempt_count"] == 1
    webhook_client.headers["Authorization"] = f"Bearer {create_access_token(MEMBER_ID)[0]}"
    assert webhook_client.get("/admin/pix/events").status_code == 403
    assert webhook_client.post(path, json={"reason": "Sem permissão"}).status_code == 403


def test_secret_never_enters_payload_response_or_logs(webhook_client, business_db, capsys):
    _, charge = charge_for(webhook_client)
    response = send(webhook_client, envelope(charge))
    assert TEST_SECRET not in response.text
    assert TEST_SECRET not in json.dumps(detail(webhook_client, response))
    with business_db.connect() as connection:
        rows = connection.execute(text("SELECT payload FROM webhook_events")).all()
        assert TEST_SECRET not in str(rows)
    captured = capsys.readouterr()
    assert TEST_SECRET not in captured.out + captured.err


def test_secret_must_be_exclusive_and_long_enough():
    with pytest.raises(ValidationError):
        Settings(pix_webhook_test_secret="short", _env_file=None)
    settings = Settings(_env_file=None)
    for reserved in [settings.jwt_secret_key, settings.redis_password, settings.postgres_password]:
        if reserved:
            value = reserved.get_secret_value()
            if len(value) >= 32:
                with pytest.raises(ValidationError):
                    Settings(pix_webhook_test_secret=value, _env_file=None)


def test_disabled_simulator_rejects_webhook_even_with_valid_signature(webhook_client, monkeypatch):
    _, charge = charge_for(webhook_client)
    data = envelope(charge)
    monkeypatch.setenv("PIX_SIMULATOR_ENABLED", "false")
    get_settings.cache_clear()
    assert send(webhook_client, data).status_code == 404


def test_migration_refuses_to_discard_persisted_events(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    send(webhook_client, envelope(charge))
    command.check(Config("alembic.ini"))
    with pytest.raises(RuntimeError, match="Downgrade bloqueado"):
        command.downgrade(Config("alembic.ini"), "20261110_03")
    assert count(business_db, WebhookEvent) == count(business_db, Payment) == 1
    with business_db.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261110_04"


def test_equivalent_json_formatting_is_an_idempotent_delivery(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    data = envelope(charge)
    first = send(webhook_client, data)
    second = send(webhook_client, raw=json.dumps(data, indent=2, sort_keys=True).encode())
    assert first.json()["id"] == second.json()["id"] and second.json()["duplicate"]
    assert count(business_db, Payment) == count(business_db, WebhookEvent) == 1


def test_initial_persistence_failure_never_applies_payment(
    webhook_client, business_db, monkeypatch
):
    _, charge = charge_for(webhook_client)

    def unavailable(*args, **kwargs):
        raise ApplicationError("database_busy", "Falha de teste", 503)

    monkeypatch.setattr("app.modules.webhooks.services.record_event", unavailable)
    assert send(webhook_client, envelope(charge)).status_code == 503
    assert count(business_db, WebhookEvent) == count(business_db, Payment) == 0


def test_failure_recording_unavailable_keeps_durable_event_recoverable(
    webhook_client,
    business_db,
    monkeypatch,
):
    _, charge = charge_for(webhook_client)
    data = envelope(charge)

    def failed_processing(*args, **kwargs):
        raise RuntimeError("internal-processing-test-failure")

    def failed_recording(*args, **kwargs):
        raise ApplicationError("database_busy", "Banco indisponível no teste", 503)

    with monkeypatch.context() as patch:
        patch.setattr("app.modules.payments.services.record_event", failed_processing)
        patch.setattr(
            "app.modules.webhooks.services.WebhookService._record_failure", failed_recording
        )
        assert send(webhook_client, data).status_code == 503
    with Session(business_db) as session:
        event = session.scalar(select(WebhookEvent))
        assert event.status == "received" and event.attempt_count == 0
    assert count(business_db, Payment) == 0
    assert send(webhook_client, data).json()["status"] == "processed"
    assert count(business_db, WebhookEvent) == count(business_db, Payment) == 1


def test_two_different_charge_receipts_never_settle_same_fee_twice(webhook_client, business_db):
    from test_pix_foundation import create_charge

    fee, charge = charge_for(webhook_client)
    other = create_charge(webhook_client, fee["id"]).json()
    assert send(webhook_client, envelope(charge)).json()["status"] == "processed"
    rejected = send(webhook_client, envelope(other))
    assert rejected.json()["status"] == "rejected"
    assert count(business_db, WebhookEvent) == 2 and count(business_db, Payment) == 1
