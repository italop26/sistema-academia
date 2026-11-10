import logging

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.modules.health.repositories import HealthRepository
from app.modules.health.schemas import HealthResponse

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(self, repository: HealthRepository, redis: Redis):
        self.repository = repository
        self.redis = redis

    def check(self) -> HealthResponse:
        database = redis = "unavailable"
        try:
            if self.repository.ping():
                database = "ok"
        except SQLAlchemyError:
            logger.warning("Banco de dados indisponível na verificação de saúde")
        try:
            if self.redis.ping():
                redis = "ok"
        except RedisError:
            logger.warning("Redis indisponível na verificação de saúde")
        return HealthResponse(
            status="ok" if database == redis == "ok" else "degraded",
            database=database,
            redis=redis,
        )
