import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_business import ADMIN_ID
from test_business import business_client as business_client
from test_business import business_db as business_db
from test_pix_foundation import create_charge, fee_for
from test_pix_foundation import pix_client as pix_client

from app.core.config import get_settings
from app.modules.billing.models import MonthlyFee
from app.modules.payments.models import Charge, Payment
from app.modules.webhooks.models import WebhookEvent
from app.modules.webhooks.repositories import WebhookRepository
from app.modules.webhooks.schemas import SimulatedEvent
from app.modules.webhooks.services import WebhookService

TEST_SECRET = "isolated-webhook-only-test-secret-12345678"
WEBHOOK_PATH = "/webhooks/pix/simulated"


@pytest.fixture
def webhook_client(pix_client, monkeypatch):
    monkeypatch.setenv("PIX_WEBHOOK_TEST_SECRET", TEST_SECRET)
    get_settings.cache_clear()
    yield pix_client
    get_settings.cache_clear()


def charge_for(client):
    fee = fee_for(client)
    response = create_charge(client, fee["id"])
    assert response.status_code == 200, response.text
    return fee, response.json()


def envelope(charge, event_type="payment.confirmed", **overrides):
    data = {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "event_type": event_type,
        "is_simulated": True,
        "charge_id": charge["id"],
        "reference": charge["reference"],
        "amount_cents": charge["amount_cents"],
        "currency": "BRL",
        "occurred_at": charge["created_at"],
    }
    if event_type == "payment.confirmed":
        data["external_payment_id"] = f"TEST-PAY-{uuid4()}"
    return {**data, **overrides}


def send(client, payload=None, *, secret=TEST_SECRET, timestamp=None, raw=None):
    body = raw if raw is not None else json.dumps(payload, separators=(",", ":")).encode()
    stamp = str(int(time.time())) if timestamp is None else str(timestamp)
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post(
        WEBHOOK_PATH,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Pix-Test-Timestamp": stamp,
            "X-Pix-Test-Signature": f"sha256={signature}",
        },
    )


def detail(client, response):
    result = client.get(f"/admin/pix/events/{response.json()['id']}")
    assert result.status_code == 200, result.text
    return result.json()


def test_authenticated_webhook_applies_one_payment(webhook_client, business_db):
    fee, charge = charge_for(webhook_client)
    response = send(webhook_client, envelope(charge))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processed"
    assert response.json()["is_simulated"] and response.json()["duplicate"] is False
    event = detail(webhook_client, response)
    assert event["attempt_count"] == event["delivery_count"] == 1
    assert event["payment_id"] and event["result_code"] == "payment_applied"
    fee_result = webhook_client.get(f"/admin/monthly-fees/{fee['id']}").json()
    assert fee_result["completed"] and fee_result["is_simulated"]
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 1


def test_identical_delivery_is_durable_and_idempotent(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    payload = envelope(charge)
    first = send(webhook_client, payload)
    repeated = send(webhook_client, payload)
    assert first.json()["id"] == repeated.json()["id"]
    assert repeated.json()["duplicate"] is True
    event = detail(webhook_client, repeated)
    assert event["delivery_count"] == 2 and event["attempt_count"] == 1
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1


def test_missing_or_false_signature_never_creates_event(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    payload = envelope(charge)
    assert webhook_client.post(WEBHOOK_PATH, json=payload).status_code == 401
    assert send(webhook_client, payload, secret="wrong-test-secret").status_code == 401
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(WebhookEvent)) == 0
        assert session.scalar(select(func.count()).select_from(Payment)) == 0


def test_event_content_conflict_preserves_original(webhook_client):
    _, charge = charge_for(webhook_client)
    payload = envelope(charge)
    original = send(webhook_client, payload)
    conflict = send(webhook_client, {**payload, "amount_cents": 1})
    assert conflict.status_code == 409
    event = detail(webhook_client, original)
    assert event["status"] == "processed" and event["conflict_count"] == 1
    assert event["payload"]["amount_cents"] == charge["amount_cents"]
    assert event["delivery_count"] == 2


def test_failure_is_durable_and_admin_retry_recovers(webhook_client, business_db, monkeypatch):
    fee, charge = charge_for(webhook_client)
    payload = envelope(charge)

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive-provider-failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.modules.payments.services.record_event", fail)
        response = send(webhook_client, payload)
    assert response.status_code == 202
    failed = detail(webhook_client, response)
    assert failed["status"] == "failed" and failed["attempt_count"] == 1
    assert failed["last_error_code"] == "processing_failed"
    assert "sensitive" not in json.dumps(failed)
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == "pendente"
        assert session.get(Charge, charge["id"]).status == "pending"
        assert session.scalar(select(func.count()).select_from(Payment)) == 0
    retry = webhook_client.post(
        f"/admin/pix/events/{failed['id']}/retry", json={"reason": "Falha corrigida no teste"}
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "processed" and retry.json()["attempt_count"] == 2
    assert retry.json()["last_error_code"] is None
    history = webhook_client.get(
        "/admin/history",
        params={
            "entity_type": "webhook_event",
            "entity_id": failed["id"],
        },
    ).json()
    assert any(event["action"] == "retried" and event["actor_id"] == ADMIN_ID for event in history)


def test_received_event_can_recover_after_interruption(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    payload = envelope(charge)
    with Session(business_db) as session:
        event, _ = WebhookService(WebhookRepository(session)).receive(
            SimulatedEvent.model_validate(payload)
        )
    assert event.status == "received" and event.attempt_count == 0
    response = send(webhook_client, payload)
    assert response.json()["duplicate"] and response.json()["status"] == "processed"


def test_divergent_amount_is_saved_but_not_settled(webhook_client, business_db):
    _, charge = charge_for(webhook_client)
    response = send(webhook_client, envelope(charge, amount_cents=1))
    assert response.status_code == 202
    event = detail(webhook_client, response)
    assert event["status"] == "rejected" and event["last_error_code"] == "amount_mismatch"
    assert (
        webhook_client.post(
            f"/admin/pix/events/{event['id']}/retry", json={"reason": "Não alterar rejeição"}
        ).status_code
        == 409
    )
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 0


def test_event_admin_reads_and_retries_require_admin(webhook_client):
    _, charge = charge_for(webhook_client)
    response = send(webhook_client, envelope(charge))
    event_id = response.json()["id"]
    webhook_client.headers.pop("Authorization")
    assert webhook_client.get("/admin/pix/events").status_code == 401
    assert webhook_client.get(f"/admin/pix/events/{event_id}").status_code == 401
    assert (
        webhook_client.post(
            f"/admin/pix/events/{event_id}/retry", json={"reason": "Sem permissão"}
        ).status_code
        == 401
    )


def test_filter_lists_only_matching_event_status(webhook_client):
    _, charge = charge_for(webhook_client)
    send(webhook_client, envelope(charge, amount_cents=1))
    response = webhook_client.get("/admin/pix/events", params={"status": "rejected", "limit": 1})
    assert response.status_code == 200 and len(response.json()) == 1
    assert response.json()[0]["status"] == "rejected"


def test_webhook_requires_its_own_secret(pix_client, monkeypatch):
    monkeypatch.delenv("PIX_WEBHOOK_TEST_SECRET", raising=False)
    get_settings.cache_clear()
    assert send(pix_client, {}).status_code == 404
