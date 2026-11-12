from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_business import ADMIN_ID, MEMBER_ID, create_records, generate
from test_business import business_client as business_client
from test_business import business_db as business_db

from app.core.config import Settings, get_settings
from app.core.errors import ApplicationError
from app.core.security import create_access_token
from app.modules.audit.models import AuditEvent
from app.modules.billing.models import MonthlyFee
from app.modules.billing.repositories import BillingRepository
from app.modules.billing.schemas import PaymentCreate
from app.modules.billing.services import BillingService
from app.modules.payments.models import Charge, Payment
from app.modules.payments.providers import (
    SIMULATION_NOTICE,
    ChargeRequest,
    SimulatedPixProvider,
    get_pix_provider,
)
from app.modules.payments.repositories import PaymentRepository
from app.modules.payments.schemas import ChargeCreate, SimulatedReceipt
from app.modules.payments.services import ChargeService, SettlementService


@pytest.fixture
def pix_client(business_client, monkeypatch):
    monkeypatch.setenv("PIX_SIMULATOR_ENABLED", "true")
    get_settings.cache_clear()
    yield business_client
    get_settings.cache_clear()


def fee_for(client):
    _, _, enrollment = create_records(client)
    return generate(client, enrollment["id"]).json()


def create_charge(client, fee_id, key=None, ttl=3600):
    return client.post(
        "/admin/pix/charges",
        json={
            "monthly_fee_id": fee_id,
            "idempotency_key": key or str(uuid4()),
            "expires_in_seconds": ttl,
        },
    )


def receipt(charge, external_id=None):
    return SimulatedReceipt(
        charge_id=charge["id"],
        reference=charge["reference"],
        external_payment_id=external_id or f"TEST-PAY-{uuid4()}",
        amount_cents=charge["amount_cents"],
    )


def settle(engine, data):
    with Session(engine) as session:
        return SettlementService(session).settle_simulated(data)


def test_simulator_is_disabled_by_default_and_blocked_in_production(business_client, monkeypatch):
    monkeypatch.delenv("PIX_SIMULATOR_ENABLED", raising=False)
    get_settings.cache_clear()
    assert Settings(_env_file=None).pix_simulator_enabled is False
    fee = fee_for(business_client)
    assert create_charge(business_client, fee["id"]).status_code == 404
    with pytest.raises(ValidationError, match="produção"):
        Settings(app_env="production", pix_simulator_enabled=True, _env_file=None)
    production = Settings(app_env="production", _env_file=None).model_copy(
        update={"pix_simulator_enabled": True}
    )
    monkeypatch.setattr("app.modules.payments.providers.get_settings", lambda: production)
    with pytest.raises(ApplicationError) as error:
        get_pix_provider()
    assert error.value.status_code == 404


def test_provider_contract_is_local_deterministic_and_not_payable():
    provider = SimulatedPixProvider()
    request = ChargeRequest(
        str(uuid4()), str(uuid4()), 19990, "BRL", datetime.now(UTC) + timedelta(hours=1)
    )
    first, second = provider.create_charge(request), provider.create_charge(request)
    assert first == second
    assert first.reference.startswith("TEST-PIX-")
    assert provider.is_simulated is True
    assert not hasattr(first, "qr_code")


def test_charge_is_separate_from_fee_and_has_test_notice(pix_client, business_db):
    fee = fee_for(pix_client)
    response = create_charge(pix_client, fee["id"])
    assert response.status_code == 200, response.text
    charge = response.json()
    assert charge["monthly_fee_id"] == fee["id"]
    assert charge["amount_cents"] == fee["amount_cents"]
    assert charge["currency"] == "BRL" and charge["status"] == "pending"
    assert charge["is_simulated"] and charge["simulation_notice"] == SIMULATION_NOTICE
    assert charge["payment_code"] is None and charge["reference"].startswith("TEST-PIX-")
    assert charge["created_by"] == ADMIN_ID
    assert pix_client.get(f"/admin/monthly-fees/{fee['id']}").json()["completed"] is False
    listed = pix_client.get("/admin/pix/charges", params={"monthly_fee_id": fee["id"]})
    assert [item["id"] for item in listed.json()] == [charge["id"]]
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 0
        event = session.scalar(select(AuditEvent).where(AuditEvent.entity_id == charge["id"]))
        assert event.actor_type == "admin"


def test_charge_idempotency_and_conflicting_key(pix_client, business_db):
    fee = fee_for(pix_client)
    key = str(uuid4())
    first = create_charge(pix_client, fee["id"], key).json()
    second = create_charge(pix_client, fee["id"], key).json()
    assert first == second
    assert create_charge(pix_client, fee["id"], key, ttl=120).status_code == 409
    other = fee_for(pix_client)
    assert create_charge(pix_client, other["id"], key).status_code == 409
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Charge)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.entity_id == first["id"],
                )
            )
            == 1
        )


@pytest.mark.parametrize("ttl", [0, 59, 86401, True, 60.5, "60"])
def test_invalid_charge_input(pix_client, ttl):
    fee = fee_for(pix_client)
    assert create_charge(pix_client, fee["id"], ttl=ttl).status_code == 422


def test_client_cannot_supply_provider_amount_or_simulation_flag(pix_client):
    fee = fee_for(pix_client)
    for extra in [{"provider": "real"}, {"amount_cents": 1}, {"is_simulated": False}]:
        assert (
            pix_client.post(
                "/admin/pix/charges",
                json={
                    "monthly_fee_id": fee["id"],
                    "idempotency_key": str(uuid4()),
                    **extra,
                },
            ).status_code
            == 422
        )


@pytest.mark.parametrize("role,status", [(None, 401), (MEMBER_ID, 403)])
def test_charge_routes_require_admin(pix_client, role, status):
    pix_client.headers.pop("Authorization")
    if role:
        pix_client.headers["Authorization"] = f"Bearer {create_access_token(role)[0]}"
    assert pix_client.post("/admin/pix/charges", json={}).status_code == status
    assert pix_client.get("/admin/pix/charges").status_code == status
    assert pix_client.get(f"/admin/pix/charges/{uuid4()}").status_code == status


def test_no_public_webhook_or_simulated_payment_route_in_stage_one(pix_client):
    assert pix_client.post("/webhooks/pix", json={}).status_code == 404
    assert pix_client.post("/admin/pix/pay", json={}).status_code == 404


def test_manual_payment_closes_test_charges_and_keeps_legacy_contract(pix_client):
    fee = fee_for(pix_client)
    charges = [create_charge(pix_client, fee["id"]).json() for _ in range(2)]
    result = pix_client.post(
        f"/admin/monthly-fees/{fee['id']}/pay",
        json={
            "amount_cents": fee["amount_cents"],
            "note": "Recebimento manual preservado",
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["completed"] and result.json()["is_simulated"] is False
    payment = pix_client.get(f"/admin/monthly-fees/{fee['id']}/payment").json()
    assert payment["actor_id"] == ADMIN_ID and payment["method"] == "manual"
    assert payment["note"] == "Recebimento manual preservado" and payment["charge_id"] is None
    for charge in charges:
        assert pix_client.get(f"/admin/pix/charges/{charge['id']}").json()["status"] == "cancelled"
    assert create_charge(pix_client, fee["id"]).status_code == 409


def test_fee_cancellation_closes_test_charges(pix_client):
    fee = fee_for(pix_client)
    charge = create_charge(pix_client, fee["id"]).json()
    assert (
        pix_client.post(
            f"/admin/monthly-fees/{fee['id']}/cancel",
            json={
                "reason": "Dispensa registrada",
            },
        ).status_code
        == 200
    )
    assert pix_client.get(f"/admin/pix/charges/{charge['id']}").json()["status"] == "cancelled"
    assert create_charge(pix_client, fee["id"]).status_code == 409


def test_shared_settlement_marks_simulation_and_system_history(pix_client, business_db):
    fee = fee_for(pix_client)
    charge = create_charge(pix_client, fee["id"]).json()
    data = receipt(charge)
    first, repeated = settle(business_db, data), settle(business_db, data)
    assert first.completed and first.is_simulated and first.payment_method == "pix"
    assert repeated.paid_at == first.paid_at and repeated.id == first.id
    assert first.simulation_notice == SIMULATION_NOTICE
    payment = pix_client.get(f"/admin/monthly-fees/{fee['id']}/payment").json()
    assert payment["method"] == "pix" and payment["actor_id"] is None and payment["is_simulated"]
    history = pix_client.get(
        "/admin/history",
        params={
            "entity_type": "monthly_fee",
            "entity_id": fee["id"],
        },
    ).json()
    paid = [item for item in history if item["action"] == "paid"]
    assert len(paid) == 1 and paid[0]["actor_type"] == "system" and paid[0]["actor_id"] is None
    assert (
        pix_client.post(
            f"/admin/monthly-fees/{fee['id']}/pay",
            json={
                "amount_cents": fee["amount_cents"],
                "note": "Não duplicar recebimento",
            },
        ).status_code
        == 409
    )
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1


def test_shared_settlement_rejects_bad_reference_amount_and_expiration(
    pix_client, business_db, monkeypatch
):
    fee = fee_for(pix_client)
    charge = create_charge(pix_client, fee["id"]).json()
    data = receipt(charge)
    for changes in [{"reference": "TEST-PIX-unknown"}, {"amount_cents": 1}]:
        with pytest.raises(ApplicationError):
            settle(business_db, data.model_copy(update=changes))
    future = datetime.fromisoformat(charge["expires_at"].replace("Z", "+00:00")) + timedelta(
        seconds=1
    )
    monkeypatch.setattr("app.modules.payments.services.utcnow", lambda: future)
    assert pix_client.get(f"/admin/pix/charges/{charge['id']}").json()["status"] == "expired"
    with pytest.raises(ApplicationError):
        settle(business_db, data)
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == "pendente"
        assert session.scalar(select(func.count()).select_from(Payment)) == 0


def test_charge_creation_rolls_back_when_history_fails(pix_client, business_db, monkeypatch):
    fee = fee_for(pix_client)

    def fail(*args, **kwargs):
        raise ApplicationError("history_failed", "Falha simulada", 503)

    monkeypatch.setattr("app.modules.payments.services.record_event", fail)
    assert create_charge(pix_client, fee["id"]).status_code == 503
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Charge)) == 0


def test_simulated_settlement_rolls_back_all_records_when_history_fails(
    pix_client,
    business_db,
    monkeypatch,
):
    fee = fee_for(pix_client)
    charge = create_charge(pix_client, fee["id"]).json()
    with Session(business_db) as session:
        count_before = session.scalar(select(func.count()).select_from(AuditEvent))

    def fail(*args, **kwargs):
        raise ApplicationError("history_failed", "Falha simulada", 503)

    monkeypatch.setattr("app.modules.payments.services.record_event", fail)
    with pytest.raises(ApplicationError):
        settle(business_db, receipt(charge))
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == "pendente"
        assert session.get(Charge, charge["id"]).status == "pending"
        assert session.scalar(select(func.count()).select_from(Payment)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == count_before


def test_concurrent_charge_creation_is_idempotent(pix_client, business_db):
    fee = fee_for(pix_client)
    data = ChargeCreate(monthly_fee_id=fee["id"], idempotency_key=uuid4())

    def create(_):
        with Session(business_db) as session:
            return ChargeService(PaymentRepository(session)).create(data, ADMIN_ID).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(create, range(2)))
    assert ids[0] == ids[1]


def test_manual_and_simulated_settlement_cannot_both_pay(pix_client, business_db):
    fee = fee_for(pix_client)
    charge = create_charge(pix_client, fee["id"]).json()
    data = receipt(charge)

    def pay(kind):
        try:
            if kind == "pix":
                return settle(business_db, data).payment_method
            with Session(business_db) as session:
                return (
                    BillingService(BillingRepository(session))
                    .pay(
                        fee["id"],
                        PaymentCreate(amount_cents=fee["amount_cents"], note="Baixa manual"),
                        ADMIN_ID,
                    )
                    .payment_method
                )
        except ApplicationError as error:
            assert error.status_code == 409
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(pay, ["manual", "pix"]))
    assert results.count("blocked") == 1
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == fee["id"],
                AuditEvent.action == "paid",
            )
        ).all()
        assert len(events) == 1


def test_database_rejects_second_payment_across_methods(pix_client, business_db):
    fee = fee_for(pix_client)
    charge = create_charge(pix_client, fee["id"]).json()
    settle(business_db, receipt(charge))
    with Session(business_db) as session:
        with pytest.raises(IntegrityError), session.begin():
            session.add(
                Payment(
                    monthly_fee_id=fee["id"],
                    amount_cents=fee["amount_cents"],
                    actor_id=ADMIN_ID,
                    note="Duplicado",
                )
            )
            session.flush()


def test_migration_preserves_existing_manual_payments_and_history(business_client, business_db):
    fee = fee_for(business_client)
    assert (
        business_client.post(
            f"/admin/monthly-fees/{fee['id']}/pay",
            json={
                "amount_cents": fee["amount_cents"],
                "note": "Histórico anterior",
            },
        ).status_code
        == 200
    )
    payment = business_client.get(f"/admin/monthly-fees/{fee['id']}/payment").json()
    config = Config("alembic.ini")
    command.downgrade(config, "20261110_02")
    with business_db.connect() as connection:
        old = connection.execute(text("SELECT * FROM manual_payments")).mappings().one()
        history = connection.execute(
            text('SELECT id, actor_id, "before", "after" FROM audit_events ORDER BY id')
        ).all()
    command.upgrade(config, "head")
    command.check(config)
    with business_db.connect() as connection:
        current = (
            connection.execute(
                text(
                    "SELECT id, monthly_fee_id, amount_cents, actor_id, note, paid_at FROM payments"
                )
            )
            .mappings()
            .one()
        )
        assert dict(current) == dict(old)
        assert (
            connection.execute(
                text('SELECT id, actor_id, "before", "after" FROM audit_events ORDER BY id')
            ).all()
            == history
        )
    assert "manual_payments" not in inspect(business_db).get_table_names()
    restored = business_client.get(f"/admin/monthly-fees/{fee['id']}/payment").json()
    assert restored["id"] == payment["id"] and restored["note"] == "Histórico anterior"


def test_downgrade_refuses_to_discard_charge_history(pix_client, business_db):
    fee = fee_for(pix_client)
    charge = create_charge(pix_client, fee["id"]).json()
    with pytest.raises(RuntimeError, match="Downgrade bloqueado"):
        command.downgrade(Config("alembic.ini"), "20261110_02")
    assert pix_client.get(f"/admin/pix/charges/{charge['id']}").status_code == 200
    with business_db.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261110_03"
