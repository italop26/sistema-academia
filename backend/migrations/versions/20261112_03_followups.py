"""Estados simples de acompanhamento sobre as detecções. Revision: 20261112_03."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20261112_03"
down_revision = "20261112_02"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("absence_detections") as batch:
        batch.add_column(
            sa.Column("status", sa.String(20), nullable=False, server_default="pendente")
        )
        batch.add_column(sa.Column("assigned_to", sa.String(36)))
        batch.add_column(sa.Column("last_note", sa.String(500)))
        batch.add_column(sa.Column("closed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_foreign_key(
            "fk_absence_detections_assigned_to_users",
            "users",
            ["assigned_to"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "status", "status IN ('pendente', 'em_acompanhamento', 'resolvido', 'encerrado')"
        )
        batch.create_check_constraint("version", "version >= 1")
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE absence_detections SET status = 'resolvido', "
            "last_note = 'Retorno anterior à implantação do acompanhamento.', "
            "closed_at = (SELECT MIN(occurred_at) FROM check_ins WHERE "
            "check_ins.student_id = absence_detections.student_id AND occurred_at >= detected_at) "
            "WHERE EXISTS (SELECT 1 FROM check_ins WHERE "
            "check_ins.student_id = absence_detections.student_id AND occurred_at >= detected_at)"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE absence_detections SET status = 'encerrado', "
            "last_note = 'Episódio substituído por detecção posterior.', closed_at = detected_at "
            "WHERE status = 'pendente' AND EXISTS (SELECT 1 FROM absence_detections newer "
            "WHERE newer.student_id = absence_detections.student_id AND "
            "(newer.detected_at > absence_detections.detected_at OR "
            "(newer.detected_at = absence_detections.detected_at "
            "AND newer.id > absence_detections.id)))"
        )
    )
    audit = sa.table(
        "audit_events",
        sa.column("id", sa.String()),
        sa.column("entity_type", sa.String()),
        sa.column("entity_id", sa.String()),
        sa.column("action", sa.String()),
        sa.column("actor_type", sa.String()),
        sa.column("reason", sa.String()),
        sa.column("before", sa.JSON()),
        sa.column("after", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for row in connection.execute(
        sa.text("SELECT id, status, last_note FROM absence_detections WHERE status <> 'pendente'")
    ).mappings():
        connection.execute(
            audit.insert().values(
                id=str(uuid4()),
                entity_type="absence_detection",
                entity_id=row["id"],
                action="workflow_initialized",
                actor_type="system",
                reason=row["last_note"],
                before={"status": "pendente"},
                after={"status": row["status"]},
                created_at=datetime.now(UTC),
            )
        )
    with op.batch_alter_table("absence_detections") as batch:
        batch.create_check_constraint(
            "closure",
            "(status IN ('pendente', 'em_acompanhamento') AND closed_at IS NULL) OR "
            "(status IN ('resolvido', 'encerrado') AND closed_at IS NOT NULL)",
        )
    op.create_index(
        "uq_absence_open_student",
        "absence_detections",
        ["student_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('pendente', 'em_acompanhamento')"),
        postgresql_where=sa.text("status IN ('pendente', 'em_acompanhamento')"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM absence_detections")):
        raise RuntimeError("Downgrade bloqueado: existem acompanhamentos. Preserve o histórico.")
    op.drop_index("uq_absence_open_student", table_name="absence_detections")
    with op.batch_alter_table("absence_detections") as batch:
        batch.drop_constraint(op.f("ck_absence_detections_closure"), type_="check")
        batch.drop_constraint(op.f("ck_absence_detections_version"), type_="check")
        batch.drop_constraint(op.f("ck_absence_detections_status"), type_="check")
        batch.drop_constraint("fk_absence_detections_assigned_to_users", type_="foreignkey")
        for field in ("status", "assigned_to", "last_note", "closed_at", "version"):
            batch.drop_column(field)
