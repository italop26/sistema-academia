"""Deterministic worker-crash probe, imported ONLY by the disposable test composition."""

import os
import time
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.modules.notifications.sender import SimulatedReminderSender


def guard():
    settings = get_settings()
    if (
        os.getenv("VALIDATION_ONLY") != "1"
        or settings.app_env != "test"
        or settings.database_url.database != "./data/validation.db"
    ):
        raise SystemExit("Probe permitido somente no banco descartável validation.db.")


if __name__ == "__main__":
    guard()
    original_send = SimulatedReminderSender.send

    def controlled_send(self, data):
        pause = Path("/app/data/notification-pause")
        if pause.exists():
            Path("/app/data/notification-inside-sender").write_text("entered", encoding="utf8")
            while pause.exists():
                time.sleep(0.05)
        return original_send(self, data)

    SimulatedReminderSender.send = controlled_send
    celery_app.worker_main(["worker", "--loglevel=WARNING", "--concurrency=1"])
