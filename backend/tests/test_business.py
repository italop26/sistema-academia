from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import build_engine, get_business_session, get_engine, get_session
from app.core.domain import ReasonRequest
from app.core.errors import ApplicationError
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.billing.models import ManualPayment, MonthlyFee
from app.modules.billing.repositories import BillingRepository
from app.modules.billing.schemas import GenerateFee, PaymentCreate
from app.modules.billing.services import BillingService, fee_public
from app.modules.plans.models import Plan
from app.modules.students.models import Student
from app.modules.users.models import User, UserRole

ADMIN_ID = "11111111-1111-4111-8111-111111111111"
MEMBER_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def business_db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.modules.billing.presenters.local_today", lambda: date(2028, 2, 1))
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+pysqlite:///{(tmp_path / 'business.db').as_posix()}"
    )
    get_settings.cache_clear()
    get_engine.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    engine = build_engine(get_settings().database_url)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                User(
                    id=ADMIN_ID,
                    name="Admin",
                    email="admin@tests.example",
                    password_hash="unused",
                    role=UserRole.ADMIN,
                ),
                User(
                    id=MEMBER_ID,
                    name="Member",
                    email="member@tests.example",
                    password_hash="unused",
                    role=UserRole.MEMBER,
                ),
            ]
        )
    yield engine
    engine.dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def business_client(business_db) -> Iterator[TestClient]:
    app = create_app()

    def session_dependency():
        with Session(business_db, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_business_session] = session_dependency
    redis = Mock()
    redis.exists.return_value = False
    app.dependency_overrides[get_redis] = lambda: redis
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {create_access_token(ADMIN_ID)[0]}"
        yield client


def create_records(client, *, name="Aluno A", starts_on="2028-01-01", ends_on=None, due_day=31):
    student = client.post("/admin/students", json={"name": name, "email": "aluno@example.com"})
    assert student.status_code == 201, student.text
    plan = client.post("/admin/plans", json={"name": "Pilates", "monthly_amount_cents": 19990})
    assert plan.status_code == 201, plan.text
    enrollment = client.post(
        "/admin/enrollments",
        json={
            "student_id": student.json()["id"],
            "plan_id": plan.json()["id"],
            "starts_on": starts_on,
            "ends_on": ends_on,
            "due_day": due_day,
        },
    )
    assert enrollment.status_code == 201, enrollment.text
    return student.json(), plan.json(), enrollment.json()


def generate(client, enrollment_id, competence="2028-02"):
    return client.post(
        "/admin/monthly-fees/generate",
        json={
            "enrollment_id": enrollment_id,
            "competence": competence,
        },
    )


def test_registration_validation_relationships_and_audit(business_client, business_db):
    student, plan, enrollment = create_records(business_client)
    assert enrollment["amount_cents"] == plan["monthly_amount_cents"]
    assert enrollment["student_id"] == student["id"]
    assert business_client.get(f"/admin/students/{student['id']}").status_code == 200
    for kind, record in [("student", student), ("plan", plan), ("enrollment", enrollment)]:
        events = business_client.get(
            "/admin/history",
            params={
                "entity_type": kind,
                "entity_id": record["id"],
            },
        ).json()
        assert len(events) == 1
        assert events[0]["actor_id"] == ADMIN_ID
        assert events[0]["after"]["id"] == record["id"]
    with Session(business_db) as session:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, "19990", 2_000_000_001])
def test_plan_rejects_invalid_money(business_client, amount):
    response = business_client.post(
        "/admin/plans",
        json={
            "name": "Plano",
            "monthly_amount_cents": amount,
        },
    )
    assert response.status_code == 422


def test_student_validation_and_optional_account_link(business_client):
    for data in [
        {"name": "   "},
        {"name": "Aluno", "email": "invalid"},
        {"name": "Aluno", "role": ADMIN_ID},
    ]:
        assert business_client.post("/admin/students", json=data).status_code == 422
    assert (
        business_client.post(
            "/admin/students",
            json={
                "name": "Aluno",
                "user_id": str(uuid4()),
            },
        ).status_code
        == 404
    )


def test_duplicate_enrollment_and_invalid_dates(business_client):
    student, plan, _ = create_records(business_client)
    data = {
        "student_id": student["id"],
        "plan_id": plan["id"],
        "starts_on": "2028-01-01",
        "due_day": 10,
    }
    assert business_client.post("/admin/enrollments", json=data).status_code == 409
    assert (
        business_client.post(
            "/admin/enrollments",
            json={
                **data,
                "ends_on": "2027-12-31",
            },
        ).status_code
        == 422
    )
    for day in [0, 32, True]:
        assert (
            business_client.post(
                "/admin/enrollments",
                json={
                    **data,
                    "due_day": day,
                },
            ).status_code
            == 422
        )


@pytest.mark.parametrize("kind", ["students", "plans"])
def test_inactive_records_block_new_enrollment(business_client, kind):
    student, plan, enrollment = create_records(business_client)
    business_client.post(
        f"/admin/enrollments/{enrollment['id']}/cancel", json={"reason": "Encerramento solicitado"}
    )
    target = student if kind == "students" else plan
    assert (
        business_client.post(
            f"/admin/{kind}/{target['id']}/deactivate", json={"reason": "Registro desativado"}
        ).status_code
        == 200
    )
    assert (
        business_client.post(
            "/admin/enrollments",
            json={
                "student_id": student["id"],
                "plan_id": plan["id"],
                "starts_on": "2028-01-01",
                "due_day": 10,
            },
        ).status_code
        == 409
    )


def test_plan_changes_do_not_reprice_contract_or_fee(business_client, business_db):
    _, plan, enrollment = create_records(business_client)
    with Session(business_db) as session, session.begin():
        session.get(Plan, plan["id"]).monthly_amount_cents = 30000
    response = generate(business_client, enrollment["id"])
    assert response.status_code == 200
    assert response.json()["amount_cents"] == 19990


@pytest.mark.parametrize(
    "competence,expected",
    [
        ("2028-02", "2028-02-29"),
        ("2029-02", "2029-02-28"),
        ("2028-04", "2028-04-30"),
        ("2028-12", "2028-12-31"),
    ],
)
def test_short_month_and_leap_year(business_client, competence, expected):
    _, _, enrollment = create_records(business_client)
    assert generate(business_client, enrollment["id"], competence).json()["due_on"] == expected


@pytest.mark.parametrize("competence", ["2028-2", "2028-13", "0000-01", "2028-02-01"])
def test_invalid_competence(business_client, competence):
    _, _, enrollment = create_records(business_client)
    assert generate(business_client, enrollment["id"], competence).status_code == 422


def test_competence_must_overlap_enrollment_and_no_proration(business_client):
    _, _, enrollment = create_records(business_client, starts_on="2028-02-20", ends_on="2028-03-05")
    assert generate(business_client, enrollment["id"], "2028-01").status_code == 409
    assert generate(business_client, enrollment["id"], "2028-04").status_code == 409
    assert generate(business_client, enrollment["id"], "2028-02").json()["amount_cents"] == 19990


def test_repeated_generation_keeps_one_fee_and_one_history(business_client, business_db):
    _, _, enrollment = create_records(business_client)
    first = generate(business_client, enrollment["id"]).json()
    second = generate(business_client, enrollment["id"]).json()
    assert first["id"] == second["id"]
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(MonthlyFee)) == 1
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


def test_overdue_is_derived_without_mutating_history(business_client, business_db):
    _, _, enrollment = create_records(business_client)
    fee_id = generate(business_client, enrollment["id"]).json()["id"]
    with Session(business_db) as session:
        fee = session.get(MonthlyFee, fee_id)
        assert fee_public(fee, date(2028, 2, 29)).status == "pendente"
        assert fee_public(fee, date(2028, 3, 1)).status == "vencida"
        assert fee.status == "pendente"


def test_payment_completes_only_target_student_and_keeps_history(business_client):
    student_a, _, enrollment_a = create_records(business_client)
    student_b, _, enrollment_b = create_records(business_client, name="Aluno B")
    fee_a = generate(business_client, enrollment_a["id"]).json()
    fee_b = generate(business_client, enrollment_b["id"]).json()
    paid = business_client.post(
        f"/admin/monthly-fees/{fee_a['id']}/pay",
        json={
            "amount_cents": 19990,
            "note": "Recebimento manual confirmado",
        },
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paga" and paid.json()["completed"] is True
    assert paid.json()["student_id"] == student_a["id"]
    other = business_client.get(f"/admin/monthly-fees/{fee_b['id']}").json()
    assert other["status"] == "pendente" and other["completed"] is False
    assert other["student_id"] == student_b["id"]
    history = business_client.get(
        "/admin/history",
        params={
            "entity_type": "monthly_fee",
            "entity_id": fee_a["id"],
        },
    ).json()
    assert [item["action"] for item in history] == ["issued", "paid"]
    assert history[1]["before"]["status"] == "pendente"
    assert history[1]["after"]["completed"] is True
    assert history[1]["reason"] == "Recebimento manual confirmado"
    payment = business_client.get(f"/admin/monthly-fees/{fee_a['id']}/payment").json()
    assert payment["actor_id"] == ADMIN_ID and payment["amount_cents"] == 19990
    filtered = business_client.get(
        "/admin/monthly-fees",
        params={
            "student_id": student_a["id"],
            "competence": "2028-02",
        },
    ).json()
    assert [item["id"] for item in filtered] == [fee_a["id"]]


def test_repeated_payment_and_invalid_transitions(business_client, business_db):
    _, _, enrollment = create_records(business_client)
    fee = generate(business_client, enrollment["id"]).json()
    path = f"/admin/monthly-fees/{fee['id']}"
    assert (
        business_client.post(
            f"{path}/pay",
            json={
                "amount_cents": 100,
                "note": "Valor incorreto",
            },
        ).status_code
        == 409
    )
    for _ in range(2):
        assert (
            business_client.post(
                f"{path}/pay",
                json={
                    "amount_cents": 19990,
                    "note": "Baixa confirmada",
                },
            ).status_code
            == 200
        )
    assert business_client.post(f"{path}/cancel", json={"reason": "Cancelar"}).status_code == 409
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(ManualPayment)) == 1
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


def test_cancelled_fee_and_enrollment_preserve_records(business_client):
    _, _, enrollment = create_records(business_client)
    fee = generate(business_client, enrollment["id"]).json()
    path = f"/admin/monthly-fees/{fee['id']}"
    for _ in range(2):
        assert (
            business_client.post(f"{path}/cancel", json={"reason": "Dispensa registrada"}).json()[
                "status"
            ]
            == "cancelada"
        )
    assert (
        business_client.post(
            f"{path}/pay",
            json={
                "amount_cents": 19990,
                "note": "Tentativa bloqueada",
            },
        ).status_code
        == 409
    )
    assert (
        business_client.post(
            f"/admin/enrollments/{enrollment['id']}/cancel",
            json={"reason": "Encerramento solicitado"},
        ).status_code
        == 200
    )
    assert generate(business_client, enrollment["id"], "2028-03").status_code == 409
    assert generate(business_client, enrollment["id"]).json()["id"] == fee["id"]
    assert business_client.delete(path).status_code == 405


def test_db_constraints_and_restricted_deletion(business_client, business_db):
    student, _, enrollment = create_records(business_client)
    fee = generate(business_client, enrollment["id"]).json()
    with Session(business_db) as session:
        with pytest.raises(IntegrityError), session.begin():
            session.add(Plan(name="Valor fracionado inválido", monthly_amount_cents=1.5))
            session.flush()
    with Session(business_db) as session:
        with pytest.raises(IntegrityError), session.begin():
            session.add(
                MonthlyFee(
                    enrollment_id=enrollment["id"],
                    competence=date(2028, 2, 1),
                    due_on=date(2028, 2, 10),
                    amount_cents=100,
                )
            )
            session.flush()
    with Session(business_db) as session:
        with pytest.raises(IntegrityError), session.begin():
            session.delete(session.get(Student, student["id"]))
            session.flush()
    with Session(business_db) as session:
        with pytest.raises(IntegrityError), session.begin():
            session.add(
                MonthlyFee(
                    enrollment_id=enrollment["id"],
                    competence=date(2028, 3, 2),
                    due_on=date(2028, 3, 10),
                    amount_cents=100,
                )
            )
            session.flush()
    assert business_client.get(f"/admin/monthly-fees/{fee['id']}").status_code == 200


def test_failed_audit_rolls_back_payment_and_status(business_client, business_db, monkeypatch):
    _, _, enrollment = create_records(business_client)
    fee = generate(business_client, enrollment["id"]).json()

    def fail_audit(*args, **kwargs):
        raise ApplicationError("audit_failed", "Falha simulada de histórico.", 503)

    monkeypatch.setattr("app.modules.payments.services.record_event", fail_audit)
    response = business_client.post(
        f"/admin/monthly-fees/{fee['id']}/pay",
        json={
            "amount_cents": 19990,
            "note": "Pagamento de teste",
        },
    )
    assert response.status_code == 503
    with Session(business_db) as session:
        assert session.get(MonthlyFee, fee["id"]).status == "pendente"
        assert session.scalar(select(func.count()).select_from(ManualPayment)) == 0


def test_concurrent_generation_and_payment(business_client, business_db):
    _, _, enrollment = create_records(business_client)

    def generate_one(_):
        with Session(business_db) as session:
            return (
                BillingService(BillingRepository(session))
                .generate(
                    GenerateFee(enrollment_id=enrollment["id"], competence="2028-02"), ADMIN_ID
                )
                .id
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(generate_one, range(2)))
    assert ids[0] == ids[1]

    def pay_one(_):
        with Session(business_db) as session:
            return (
                BillingService(BillingRepository(session))
                .pay(
                    ids[0],
                    PaymentCreate(amount_cents=19990, note="Pagamento concorrente"),
                    ADMIN_ID,
                )
                .status
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(pay_one, range(2))) == ["paga", "paga"]
    with Session(business_db) as session:
        assert session.scalar(select(func.count()).select_from(ManualPayment)) == 1


@pytest.mark.parametrize("path", ["students", "plans", "enrollments", "monthly-fees", "history"])
@pytest.mark.parametrize("role,status", [(None, 401), (MEMBER_ID, 403)])
def test_all_business_routes_require_admin(business_client, path, role, status):
    business_client.headers.pop("Authorization")
    if role:
        business_client.headers["Authorization"] = f"Bearer {create_access_token(role)[0]}"
    assert business_client.get(f"/admin/{path}").status_code == status
    assert business_client.post(f"/admin/{path}", json={}).status_code in (status, 405)


def test_migrations_preserve_existing_user_and_match_metadata(business_db):
    command.check(Config("alembic.ini"))
    command.downgrade(Config("alembic.ini"), "20261109_01")
    with Session(business_db) as session:
        assert session.get(User, ADMIN_ID).role == UserRole.ADMIN
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))


def test_concurrent_payment_and_cancellation_leave_one_terminal_state(business_client, business_db):
    _, _, enrollment = create_records(business_client)
    fee_id = generate(business_client, enrollment["id"]).json()["id"]

    def transition(kind):
        with Session(business_db) as session:
            service = BillingService(BillingRepository(session))
            try:
                if kind == "pay":
                    return service.pay(
                        fee_id,
                        PaymentCreate(amount_cents=19990, note="Baixa concorrente"),
                        ADMIN_ID,
                    ).status
                return service.cancel(
                    fee_id, ReasonRequest(reason="Cancelamento concorrente"), ADMIN_ID
                ).status
            except ApplicationError as exc:
                assert exc.status_code == 409
                return "blocked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(transition, ["pay", "cancel"]))
    assert results.count("blocked") == 1
    with Session(business_db) as session:
        fee = session.get(MonthlyFee, fee_id)
        payments = session.scalar(select(func.count()).select_from(ManualPayment))
        assert payments == (1 if fee.status == "paga" else 0)
        events = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == fee_id)).all()
        assert len(events) == 2


def test_optional_user_link_is_unique_and_admin_reads_are_not_cached(business_client, business_db):
    data = {"name": "Aluno com conta", "user_id": MEMBER_ID}
    assert business_client.post("/admin/students", json=data).status_code == 201
    assert business_client.post("/admin/students", json=data).status_code == 409
    response = business_client.get("/admin/students")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()[0]["user_id"] == MEMBER_ID
