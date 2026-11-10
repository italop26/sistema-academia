import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.errors import error_response, register_error_handlers
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.modules.auth.routers import router as auth_router
from app.modules.health.routers import router as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API iniciada")
    yield
    get_engine().dispose()
    get_redis().close()
    logger.info("API encerrada")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Academias e Pilates — API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        request.state.request_id = uuid4().hex
        start = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "Erro não tratado",
                extra={
                    "request_id": request.state.request_id,
                    "error_type": type(exc).__name__,
                },
            )
            response = error_response(request, 500, "internal_error", "Erro interno do servidor.")
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/auth/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        logger.info(
            "Requisição HTTP",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "path": getattr(request.scope.get("route"), "path", "[unmatched]"),
                "status": response.status_code,
                "duration_ms": round((perf_counter() - start) * 1000, 2),
            },
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    return app


app = create_app()
