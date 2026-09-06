import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import DomainError
from app.core.logging import configure_logging, request_id_ctx

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Affiliate Intelligence & Automation Platform",
        version="0.1.0",
        docs_url="/docs",
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        # Erro de regra de negócio é 4xx e resposta explicada, não stack trace.
        logger.warning(
            "domain_error", extra={"code": exc.code, "path": request.url.path, **exc.details}
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    app.include_router(api_router, prefix=settings.api_prefix)

    logger.info(
        "app_started",
        extra={
            "environment": settings.app_env,
            "mock_marketplace": settings.mock_marketplace,
            "mock_ads": settings.mock_ads,
            "dry_run": settings.dry_run,
            "ai_autonomy_level": settings.ai_autonomy_level,
        },
    )
    return app


app = create_app()
