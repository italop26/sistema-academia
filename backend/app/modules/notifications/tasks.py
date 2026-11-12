from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import get_engine
from app.modules.notifications.repositories import NotificationRepository
from app.modules.notifications.services import NotificationService, dispatch_pending, scan_overdue
from app.modules.users import models as user_models  # noqa: F401 -- register FK metadata in worker


@celery_app.task(
    name="notifications.scan_overdue", ignore_result=True, soft_time_limit=15, time_limit=20
)
def identify_overdue():
    return scan_overdue()


@celery_app.task(
    name="notifications.dispatch_pending", ignore_result=True, soft_time_limit=15, time_limit=20
)
def publish_pending():
    return dispatch_pending()


@celery_app.task(
    name="notifications.deliver",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=15,
    time_limit=20,
)
def deliver_reminder(reminder_id: str, token: str):
    with Session(get_engine(), expire_on_commit=False) as session:
        return NotificationService(NotificationRepository(session)).deliver(reminder_id, token)
