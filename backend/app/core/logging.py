import json
import logging
import logging.config
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "error_type"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
            "root": {"level": level, "handlers": ["console"]},
            "loggers": {
                "uvicorn": {"handlers": ["console"], "propagate": False, "level": level},
                "uvicorn.access": {"handlers": [], "propagate": False},
                "httpx": {"handlers": ["console"], "propagate": False, "level": "WARNING"},
                "httpcore": {"handlers": ["console"], "propagate": False, "level": "WARNING"},
            },
        }
    )
