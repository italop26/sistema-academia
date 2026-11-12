from celery import Celery
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
celery_app = Celery("academia")
celery_app.conf.update(
    broker_url=settings.redis_url(0),
    result_backend=settings.redis_url(1),
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    worker_hijack_root_logger=False,
    imports=("app.modules.notifications.tasks", "app.modules.absence.tasks"),
    worker_prefetch_multiplier=1,
    broker_connection_timeout=3,
    broker_transport_options={
        "visibility_timeout": 300,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
    },
    beat_schedule={
        "identify-absence": {"task": "absence.scan", "schedule": 300.0},
        "identify-overdue": {"task": "notifications.scan_overdue", "schedule": 300.0},
        "dispatch-reminders": {"task": "notifications.dispatch_pending", "schedule": 60.0},
    },
)


@setup_logging.connect
def setup_celery_logging(**kwargs: object) -> None:
    configure_logging(settings.log_level)
