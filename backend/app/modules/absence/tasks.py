from sqlalchemy.exc import OperationalError

from app.core.celery_app import celery_app
from app.core.errors import ApplicationError
from app.modules.absence.services import RETRY_DELAYS, scan_absence
from app.modules.users import models as user_models  # noqa: F401 -- FK metadata in worker


@celery_app.task(
    bind=True,
    name="absence.scan",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=15,
    time_limit=20,
    max_retries=3,
)
def identify_absence(self):
    try:
        return scan_absence()
    except (OperationalError, ApplicationError) as error:
        if isinstance(error, ApplicationError) and error.code != "database_busy":
            raise
        if self.request.retries >= self.max_retries:
            raise
        # Retry does not carry database errors/parameters into broker payloads.
        raise self.retry(countdown=RETRY_DELAYS[self.request.retries]) from None
