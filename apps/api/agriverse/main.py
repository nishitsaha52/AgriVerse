import asyncio
import logging
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from agriverse.config import get_settings
from agriverse.db import SessionFactory, engine
from agriverse.observability import configure_observability
from agriverse.routers import (
    agent,
    auth,
    documents,
    farms,
    operations,
    reviews,
    scans,
    soil,
    weather,
)
from agriverse.services.llm_tracing import flush_llm_traces, tracing_provider
from agriverse.services.oauth_exchange import oauth_exchange_store
from agriverse.services.rate_limit import rate_limiter
from agriverse.services.storage import storage
from agriverse.services.weather import weather_service

settings = get_settings()
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    tracing_provider(settings)
    app.state.queue = None
    app.state.storage_ready = False
    try:
        await storage.ensure_bucket()
        app.state.storage_ready = True
    except Exception as exc:
        logger.error("storage_startup_failed", error=type(exc).__name__)
    try:
        app.state.queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception as exc:
        logger.error("queue_startup_failed", error=type(exc).__name__)
    yield
    await asyncio.to_thread(flush_llm_traces, settings)
    if app.state.queue is not None:
        await app.state.queue.aclose()
    await weather_service.close()
    await rate_limiter.close()
    await oauth_exchange_store.close()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json",
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.oauth_session_secret.get_secret_value(),
    same_site="lax",
    https_only=settings.app_env == "production",
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self)"
    response.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; img-src 'self' data: blob: https:; "
            "connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'"
        ),
    )
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


if settings.app_env != "production":

    @app.get("/docs", include_in_schema=False)
    async def swagger_docs(request: Request) -> HTMLResponse:
        nonce = secrets.token_urlsafe(32)
        root_path = request.scope.get("root_path", "").rstrip("/")
        page = get_swagger_ui_html(
            openapi_url=f"{root_path}{app.openapi_url}",
            title=f"{app.title} - Swagger UI",
        )
        html = bytes(page.body).decode().replace("<script>", f'<script nonce="{nonce}">')
        # Swagger needs its CDN assets and initializer; scope these allowances
        # to the documentation page while retaining the API's default policy.
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; "
                    f"script-src 'self' https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/ "
                    f"'nonce-{nonce}'; "
                    "style-src 'self' https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/ "
                    "'unsafe-inline'; "
                    "img-src 'self' data: https:; connect-src 'self'; "
                    "object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
                ),
            },
        )


@app.exception_handler(HTTPException)
async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": "Request failed",
            "status": exc.status_code,
            "detail": str(exc.detail),
            "instance": str(request.url.path),
            "request_id": request.headers.get("X-Request-Id"),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "https://agriverse.example/problems/validation",
            "title": "Validation failed",
            "status": 422,
            "detail": "One or more request fields are invalid",
            "errors": exc.errors(),
            "instance": str(request.url.path),
        },
    )


@app.get("/healthz", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readiness(request: Request) -> JSONResponse:
    database_ready = False
    try:
        async with SessionFactory() as db:
            await db.execute(text("SELECT 1"))
        database_ready = True
    except Exception:
        pass
    ready = (
        database_ready and request.app.state.queue is not None and request.app.state.storage_ready
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "degraded",
            "database": database_ready,
            "queue": request.app.state.queue is not None,
            "storage": request.app.state.storage_ready,
        },
    )


for router in (
    auth.router,
    farms.router,
    soil.router,
    weather.router,
    scans.router,
    reviews.router,
    agent.router,
    documents.router,
    operations.router,
):
    app.include_router(router, prefix=settings.api_v1_prefix)

configure_observability(app, engine.sync_engine)
