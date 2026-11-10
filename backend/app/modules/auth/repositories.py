from redis import Redis
from redis.exceptions import RedisError

from app.core.errors import ApplicationError


class TokenRepository:
    def __init__(self, redis: Redis):
        self.redis = redis

    def is_revoked(self, token_id: str) -> bool:
        try:
            return bool(self.redis.exists(f"auth:revoked:{token_id}"))
        except RedisError as exc:
            raise ApplicationError(
                "auth_unavailable", "Autenticação temporariamente indisponível.", 503
            ) from exc

    def revoke(self, token_id: str, expires_at: int) -> None:
        try:
            self.redis.set(f"auth:revoked:{token_id}", "1", exat=expires_at)
        except RedisError as exc:
            raise ApplicationError(
                "auth_unavailable", "Não foi possível confirmar a saída no servidor.", 503
            ) from exc
