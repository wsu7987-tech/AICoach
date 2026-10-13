import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.admin.router import router as admin_router
from app.api.runtime.router import router as runtime_router
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging
from app.core.readiness import ReadinessChecker
from app.core.request_context import request_id_context
from app.core.settings import Settings, get_settings
from app.db.database import Database
from app.db.readiness import DatabaseSchemaReadiness
from app.prompting.builder import PromptBuilder
from app.providers.factory import ModelProviderFactory
from app.schemas.errors import ErrorEnvelope
from app.services.config_service import ConfigError
from app.services.intent_service import IntentService
from app.services.runtime_config import DatabaseRuntimeConfigLoader
from app.services.trace_store import DatabaseTraceStore

logger = logging.getLogger(__name__)


def _request_id(request: Request, header_name: str) -> str:
    upstream_id = request.headers.get(header_name)
    if upstream_id and len(upstream_id) <= 128:
        return upstream_id
    return f"req_{uuid4().hex}"


def _error_response(request: Request, error: AppError) -> JSONResponse:
    body = ErrorEnvelope(
        request_id=getattr(request.state, "request_id", "req_unknown"),
        error_code=error.code,
        message=error.message,
    )
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return JSONResponse(
        status_code=error.status_code,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


def create_app(
    settings: Settings | None = None,
    readiness_checker: ReadinessChecker | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)
    database = Database(app_settings) if app_settings.database_url else None
    provider_factory: ModelProviderFactory | None = None
    intent_service: IntentService | None = None
    if database is not None:

        def credential_resolver(reference: str) -> str:
            # The DB stores an environment/secret reference, never the secret.
            if reference == "QWEN_API_KEY":
                return app_settings.qwen_api_key or ""
            return os.getenv(reference, "")

        provider_factory = ModelProviderFactory(
            credential_resolver, queue_wait_timeout=app_settings.provider_queue_wait_timeout
        )
        intent_service = IntentService(
            DatabaseRuntimeConfigLoader(
                database.session_factory, ttl_seconds=app_settings.runtime_config_cache_ttl_seconds
            ),
            provider_factory,
            PromptBuilder(),
            DatabaseTraceStore(database.session_factory),
        )
    checker = readiness_checker or ReadinessChecker()
    if readiness_checker is None:
        if database is None:

            async def database_not_configured() -> bool:
                return False

            checker.register("database", database_not_configured)
        else:
            checker.register("database", DatabaseSchemaReadiness(database.engine))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            if provider_factory is not None:
                await provider_factory.close()
            if database is not None:
                await database.dispose()

    app = FastAPI(
        title=app_settings.app_name,
        version="1.2.4",
        docs_url="/docs",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.database = database
    app.state.readiness_checker = checker
    app.state.intent_service = intent_service
    app.state.provider_factory = provider_factory

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = _request_id(request, app_settings.request_id_header)
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[app_settings.request_id_header] = request_id
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return response
        finally:
            request_id_context.reset(token)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if request.url.path.startswith("/api/admin/"):
            return JSONResponse(
                status_code=422,
                content={
                    "error_code": "INVALID_INPUT",
                    "message": "请求字段校验失败",
                    "issues": [
                        {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                        for e in exc.errors()
                    ],
                },
            )
        return _error_response(
            request,
            AppError(ErrorCode.INVALID_INPUT, "request validation failed", 422),
        )

    @app.exception_handler(ConfigError)
    async def config_error_handler(request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "request_id": getattr(request.state, "request_id", "req_unknown"),
                "error_code": exc.code,
                "message": exc.message,
                "issues": exc.issues,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            request,
            AppError(ErrorCode.INVALID_INPUT, str(exc.detail), exc.status_code),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled request error", exc_info=exc)
        return _error_response(
            request,
            AppError(ErrorCode.INTERNAL_ERROR, "internal server error", 500),
        )

    @app.get("/health", tags=["system"], summary="Process liveness")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["system"], summary="Service readiness")
    async def ready() -> JSONResponse:
        report = await checker.check()
        status_code = 200 if report.ready else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if report.ready else "not_ready",
                "checks": report.checks,
                "message": report.message,
            },
        )

    app.include_router(runtime_router)
    app.include_router(admin_router)
    return app


app = create_app()
