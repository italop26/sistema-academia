"""Backup, rehearsal and read-only verification of the local SQLite deployment.

Run inside the backend container with /backup mounted to an ignored local directory.
Never prints account data or environment secrets.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from app.core.config import get_settings


def inspect(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        counts = {
            table: connection.execute(
                'SELECT count(*) FROM "' + table.replace('"', '""') + '"'
            ).fetchone()[0]
            for table in tables
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return {
        "integrity": "ok",
        "foreign_keys": "ok",
        "revision": revision[0] if revision else None,
        "counts": counts,
    }


def main():
    settings = get_settings()
    if settings.database_url.get_backend_name() != "sqlite":
        raise SystemExit("Este procedimento exige o SQLite local.")
    source = Path(settings.database_url.database).resolve()
    backup = Path("/backup/academia-before.db")
    manifest = Path("/backup/manifest.json")
    mode = sys.argv[1]
    if mode == "backup":
        if backup.exists() or manifest.exists():
            raise SystemExit("Destino já existe; backup anterior preservado.")
        before = inspect(source)
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin:
            with sqlite3.connect(backup) as target:
                origin.backup(target)
        assert inspect(backup) == before
        before["sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(before, indent=2), encoding="utf8")
        print(json.dumps({"backup": "verified", **before}))
    elif mode == "rehearse":
        before = json.loads(manifest.read_text(encoding="utf8"))
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == before["sha256"]
        rehearsal = Path("/tmp/academia-migration-rehearsal.db")
        shutil.copyfile(backup, rehearsal)
        os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{rehearsal}"
        get_settings.cache_clear()
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        command.upgrade(Config("alembic.ini"), "head")
        command.check(Config("alembic.ini"))
        after = inspect(rehearsal)
        assert (
            after["revision"]
            == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        )
        for table, count in before["counts"].items():
            if table == "alembic_version":
                continue
            destination = "payments" if table == "manual_payments" else table
            assert after["counts"][destination] == count, table
        print(json.dumps({"migration_rehearsal": "passed", **after}))
    elif mode == "status":
        print(
            json.dumps(
                {
                    **inspect(source),
                    "automation_enabled": settings.financial_automation_enabled,
                    "pix_simulator_enabled": settings.pix_simulator_enabled,
                }
            )
        )
    else:
        raise SystemExit("Modo inválido.")


if __name__ == "__main__":
    main()
