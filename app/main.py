"""
FastAPI application entry point.

Startup sequence:
1. Configure structured logging
2. Initialize Prometheus metrics
3. Restore ChromaDB snapshot from GCS
4. Mount all API routes
5. Register Prometheus instrumentation middleware
"""
import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.metrics import init_app_info

# Setup logging first so all subsequent messages are structured
setup_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup tasks → yield → shutdown tasks."""
    logger.info(
        "app_starting",
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )

    # Initialize Prometheus app info metric
    init_app_info(settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT)

    # Restore ChromaDB from GCS on startup (enables persistence across instances)
    if settings.CHROMA_SYNC_TO_GCS:
        try:
            from app.services.storage import get_storage_service
            storage_svc = get_storage_service()
            restored = await storage_svc.load_chroma_from_gcs(settings.CHROMA_PERSIST_DIR)
            if restored:
                logger.info("chroma_restored_on_startup")
            else:
                logger.info("chroma_fresh_start")
        except Exception as e:
            logger.warning("chroma_restore_failed_on_startup", error=str(e))

    # Pre-warm the vector store connection
    try:
        from app.services.vector_store import get_vector_store_service
        vs = get_vector_store_service()
        total = vs.get_total_chunks()
        logger.info("vector_store_ready", total_chunks=total)
    except Exception as e:
        logger.warning("vector_store_prewarm_failed", error=str(e))

    logger.info("app_started", port=settings.PORT)
    yield

    # Graceful shutdown
    logger.info("app_shutting_down")
    if settings.CHROMA_SYNC_TO_GCS:
        try:
            from app.services.storage import get_storage_service
            await get_storage_service().save_chroma_to_gcs(settings.CHROMA_PERSIST_DIR)
            logger.info("chroma_saved_on_shutdown")
        except Exception as e:
            logger.warning("chroma_save_failed_on_shutdown", error=str(e))


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status code, and latency."""

    async def dispatch(self, request: Request, call_next) -> Response:
        import time
        import structlog.contextvars

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request.headers.get("X-Request-ID", ""),
            path=request.url.path,
            method=request.method,
        )

        t0 = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Skip logging for metrics and health endpoints (too noisy)
        if request.url.path not in (settings.METRICS_PATH, "/health/live"):
            logger.info(
                "http_request",
                status_code=response.status_code,
                latency_ms=round(elapsed_ms, 1),
            )

        structlog.contextvars.clear_contextvars()
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Production RAG application on GCP. "
            "Upload PDFs, query them using natural language, "
            "powered by Vertex AI Gemini and ChromaDB."
        ),
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(api_router, prefix="/api/v1")

    # ── Prometheus Instrumentation ───────────────────────────────────────────
    if settings.METRICS_ENABLED:
        Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,
            should_respect_env_var=False,
            excluded_handlers=[settings.METRICS_PATH, "/health/live"],
        ).instrument(app).expose(app, endpoint=settings.METRICS_PATH)

    # ── Exception Handlers ────────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. Please try again."},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=1,
        log_config=None,  # Use structlog instead of uvicorn's logging
        access_log=False,
    )
