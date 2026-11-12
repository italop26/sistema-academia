"""Same Beat application with accelerated intervals ONLY in the disposable test environment."""

from notification_test_worker import guard

from app.core.celery_app import celery_app

if __name__ == "__main__":
    guard()
    celery_app.conf.beat_schedule = {
        "identify-absence": {"task": "absence.scan", "schedule": 1.0},
        "identify-overdue": {"task": "notifications.scan_overdue", "schedule": 1.0},
        "dispatch-reminders": {"task": "notifications.dispatch_pending", "schedule": 2.0},
    }
    celery_app.start(
        [
            "beat",
            "--loglevel=WARNING",
            "--schedule=/tmp/notification-beat",
            "--pidfile=/tmp/notification-beat.pid",
        ]
    )
