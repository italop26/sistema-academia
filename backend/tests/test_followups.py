from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_absence import absence_clock as absence_clock
from test_attendance import suspend, visit
from test_business import ADMIN_ID, MEMBER_ID, create_records
from test_business import business_client as business_client
from test_business import business_db as business_db

from app.core.config import get_settings
from app.core.errors import ApplicationError
from app.core.security import create_access_token
from app.modules.absence.followups import FollowupService
from app.modules.absence.models import AbsenceDetection
from app.modules.absence.repositories import AbsenceRepository
from app.modules.absence.schemas import FollowupChange
from app.modules.absence.services import scan_absence
from app.modules.attendance.models import CheckIn
from app.modules.audit.models import AuditEvent


def prepare(client, engine, clock):
    student, _, enrollment = create_records(client)
    scan_absence(engine)
    clock.now += timedelta(hours=240)
    assert scan_absence(engine)["detected"] == 1
    with Session(engine) as session:
        detection_id = session.scalar(select(AbsenceDetection.id))
    return student, enrollment, detection_id


def change(client, detection_id, status="em_acompanhamento", version=1, note="Contato iniciado"):
    return client.post(
        f"/admin/absence/detections/{detection_id}/status",
        json={
            "status": status,
            "expected_version": version,
            "note": note,
        },
    )


def test_admin_workflow_is_audited_and_idempotent(business_client, business_db, absence_clock):
    _, _, detection_id = prepare(business_client, business_db, absence_clock)
    listing = business_client.get("/admin/absence/detections?status=pendente").json()
    assert listing[0]["student_name"] == "Aluno A" and listing[0]["version"] == 1
    first = change(business_client, detection_id)
    assert first.status_code == 200 and first.json()["assigned_to"] == ADMIN_ID
    assert change(business_client, detection_id).json() == first.json()
    stale = change(business_client, detection_id, "encerrado", note="Comando desatualizado")
    assert stale.status_code == 409
    assert (
        change(
            business_client, detection_id, "pendente", 2, "Devolver para outro contato"
        ).status_code
        == 200
    )
    resolved = change(
        business_client, detection_id, "resolvido", 3, "Contato realizado, caso resolvido"
    )
    assert resolved.status_code == 200 and resolved.json()["closed_at"] is not None
    assert change(business_client, detection_id, "pendente", 4).status_code == 409
    assert scan_absence(business_db)["detected"] == 0
    history = business_client.get(
        f"/admin/history?entity_type=absence_detection&entity_id={detection_id}"
    ).json()
    assert [row["action"] for row in history].count("status_changed") == 3
    assert len(business_client.get("/admin/absence/detections?status=resolvido").json()) == 1
    assert business_client.get("/admin/absence/detections?offset=1&limit=1").json() == []
    assert business_client.get("/admin/absence/status").json()["enabled"] is True
    assert business_client.get("/admin/absence/runs?limit=1").json()[0]["status"] == "completed"


def test_new_check_in_resolves_case_in_same_transaction(
    business_client, business_db, absence_clock
):
    student, enrollment, detection_id = prepare(business_client, business_db, absence_clock)
    response = visit(business_client, student, enrollment)
    assert response.status_code == 200
    case = business_client.get("/admin/absence/detections?status=resolvido").json()[0]
    assert case["id"] == detection_id and case["last_note"] == "Retorno registrado por check-in."
    assert scan_absence(business_db)["detected"] == 0


def test_old_check_in_replay_does_not_resolve_current_absence(
    business_client, business_db, absence_clock
):
    student, _, enrollment = create_records(business_client)
    scan_absence(business_db)
    key = str(uuid4())
    assert visit(business_client, student, enrollment, key).status_code == 200
    absence_clock.now += timedelta(hours=240)
    assert scan_absence(business_db)["detected"] == 1
    assert visit(business_client, student, enrollment, key).status_code == 200
    assert len(business_client.get("/admin/absence/detections?status=pendente").json()) == 1
    assert visit(business_client, student, enrollment).status_code == 200
    assert business_client.get("/admin/absence/detections?status=pendente").json() == []


def test_failed_resolution_audit_rolls_back_presence_and_case(
    business_client, business_db, absence_clock, monkeypatch
):
    student, enrollment, detection_id = prepare(business_client, business_db, absence_clock)

    def fail(*args, **kwargs):
        raise RuntimeError("controlled-followup-audit-failure")

    monkeypatch.setattr("app.modules.absence.followups.record_event", fail)
    assert visit(business_client, student, enrollment).status_code == 500
    with Session(business_db) as session:
        assert session.get(AbsenceDetection, detection_id).status == "pendente"
        assert session.scalar(select(func.count()).select_from(CheckIn)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_type == "check_in")
            )
            == 0
        )


@pytest.mark.parametrize("action", ["suspend", "cancel", "deactivate"])
def test_lost_eligibility_closes_open_case_on_scan(
    business_client, business_db, absence_clock, action
):
    student, enrollment, detection_id = prepare(business_client, business_db, absence_clock)
    if action == "suspend":
        assert suspend(business_client, enrollment).status_code == 200
    elif action == "cancel":
        business_client.post(
            f"/admin/enrollments/{enrollment['id']}/cancel", json={"reason": "Cancelado"}
        )
    else:
        business_client.post(
            f"/admin/students/{student['id']}/deactivate", json={"reason": "Desativado"}
        )
    assert scan_absence(business_db)["detected"] == 0
    with Session(business_db) as session:
        assert session.get(AbsenceDetection, detection_id).status == "encerrado"


def test_two_concurrent_commands_have_one_winner(business_client, business_db, absence_clock):
    _, _, detection_id = prepare(business_client, business_db, absence_clock)

    def update(target):
        with Session(business_db, expire_on_commit=False) as session:
            try:
                FollowupService(AbsenceRepository(session)).change(
                    detection_id,
                    FollowupChange(
                        status=target,
                        expected_version=1,
                        note=f"Ação {target}",
                    ),
                    ADMIN_ID,
                )
                return 200
            except ApplicationError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, ["em_acompanhamento", "encerrado"])) == [200, 409]


@pytest.mark.parametrize("role,status", [(None, 401), (MEMBER_ID, 403)])
def test_followup_routes_require_admin(business_client, absence_clock, role, status):
    business_client.headers.pop("Authorization")
    if role:
        business_client.headers["Authorization"] = f"Bearer {create_access_token(role)[0]}"
    for path in ("detections", "status", "runs"):
        assert business_client.get(f"/admin/absence/{path}").status_code == status
    assert business_client.post("/admin/absence/scan").status_code == status
    assert change(business_client, str(uuid4())).status_code == status


def test_disabled_scan_and_invalid_status_are_rejected(
    business_client, business_db, absence_clock, monkeypatch
):
    _, _, detection_id = prepare(business_client, business_db, absence_clock)
    assert change(business_client, detection_id, "inexistente").status_code == 422
    assert change(business_client, detection_id, note="").status_code == 422
    monkeypatch.setenv("ABSENCE_TRACKING_ENABLED", "false")
    get_settings.cache_clear()
    assert business_client.post("/admin/absence/scan").status_code == 409


def test_schema_and_downgrade_protect_workflow(business_client, business_db, absence_clock):
    command.check(Config("alembic.ini"))
    prepare(business_client, business_db, absence_clock)
    with pytest.raises(RuntimeError, match="Downgrade bloqueado"):
        command.downgrade(Config("alembic.ini"), "20261112_02")


def test_workflow_migration_preserves_old_detections_and_returns(
    business_client, business_db, absence_clock
):
    student, _, enrollment = create_records(business_client)
    command.downgrade(Config("alembic.ini"), "20261112_02")
    ids = [str(uuid4()), str(uuid4())]
    with business_db.begin() as connection:
        for index, row_id in enumerate(ids):
            connection.execute(
                text(
                    "INSERT INTO absence_detections "
                    "(id, student_id, rule_key, baseline_at, detected_at) "
                    "VALUES (:id, :student, 'absence-240h-v1', :baseline, :detected)"
                ),
                {
                    "id": row_id,
                    "student": student["id"],
                    "baseline": f"2028-01-0{index + 1} 12:00:00.000000",
                    "detected": f"2028-01-1{index + 1} 12:00:00.000000",
                },
            )
        connection.execute(
            text(
                "INSERT INTO check_ins "
                "(id, student_id, enrollment_id, actor_id, occurred_at, local_day) "
                "VALUES (:id, :student, :enrollment, :actor, "
                "'2028-01-20 12:00:00.000000', '2028-01-20')"
            ),
            {
                "id": str(uuid4()),
                "student": student["id"],
                "enrollment": enrollment["id"],
                "actor": ADMIN_ID,
            },
        )
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    with Session(business_db) as session:
        assert {row.status for row in session.scalars(select(AbsenceDetection))} == {"resolvido"}
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "workflow_initialized")
            )
            == 2
        )
