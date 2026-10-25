"""
app.main
========
Application entrypoint. Builds the FastAPI app via `create_app()`
(factory pattern — required for clean testing, since tests need a fresh
app instance with overridden dependencies rather than importing a
module-level singleton), wires up middleware in the correct order,
registers exception handlers that translate `BaseAppException` subclasses
into consistent JSON error bodies, mounts the v1 API router, and manages
startup/shutdown of the database engine.

RUN LOCALLY
-----------
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

The module-level `app = create_app()` at the bottom is what `uvicorn
app.main:app` imports; `create_app()` itself is what tests import
directly to get an isolated instance.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import BaseAppException
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    CorrelationIdMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import dispose_engine, engine

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "app_startup",
        environment=settings.app.environment.value,
        debug=settings.app.debug,
    )
    yield
    logger.info("app_shutdown")
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app.name,
        version="0.1.0",
        debug=settings.app.debug,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # Middleware order matters: Starlette applies them in reverse of
    # registration order to the request, so the LAST one added here runs
    # FIRST on the way in. Registering CorrelationId last means it runs
    # first among the application middleware, so every subsequent
    # middleware/handler has a correlation id available for logging.
    app.add_middleware(RateLimitMiddleware, max_requests=100, window_seconds=60)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    # CORS is registered LAST so it is the OUTERMOST middleware. Every response the
    # layers it wraps produce, including 429 rate-limit refusals, then carries the CORS
    # headers. When it sat innermost, a browser on another origin
    # (the Vite dev server on :3000 calling :8000) saw a refused request as a network
    # failure and could not read the real status or message. It also answers browser
    # preflight (OPTIONS) requests itself, so they no longer count against rate limits.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins,
        # The web client authenticates with bearer headers, not cookies.
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        # Lets a browser on another origin read the correlation id and the
        # rate-limit hint; without this they are invisible to client code.
        expose_headers=["X-Correlation-ID", "Retry-After"],
    )

    _register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.app.api_v1_prefix)

    return app


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BaseAppException)
    async def handle_app_exception(
        request: Request, exc: BaseAppException
    ) -> JSONResponse:
        logger.warning(
            "handled_exception",
            error_code=exc.error_code,
            path=request.url.path,
            details=exc.details,
        )
        content = exc.to_dict()
        content["correlation_id"] = _correlation_id(request)
        return JSONResponse(status_code=exc.http_status, content=content)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = jsonable_encoder(exc.errors())
        fields = [
            {
                "field": ".".join(str(part) for part in item.get("loc", ()) if part != "body"),
                "message": str(item.get("msg", "Invalid value")),
            }
            for item in errors[:20]
        ]
        return JSONResponse(
            status_code=422,
            content={
                # `detail` keeps the framework's original shape for existing clients.
                "detail": errors,
                "error_code": "validation_error",
                "message": "The request was not valid.",
                "details": {"errors": fields},
                "correlation_id": _correlation_id(request),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "unhandled_exception", path=request.url.path, exc_info=True
        )
        # Never leak internal exception details in the response body —
        # full detail goes to the structured log only.
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "internal_error",
                "message": "An unexpected error occurred.",
                "details": {},
                "correlation_id": _correlation_id(request),
            },
        )


app = create_app()
