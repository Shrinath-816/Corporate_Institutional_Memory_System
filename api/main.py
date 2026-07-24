"""
Module: api/main.py

Purpose:
    FastAPI application entry point for the Institutional Memory System.
    Initialises the FastAPI app, configures middleware, registers all
    routers, and manages application lifecycle events.

Responsibilities:
    - Create and configure the FastAPI application instance.
    - Register all API route modules under a versioned prefix.
    - Configure CORS, logging, and custom middleware.
    - Manage startup and shutdown lifecycle events for memory subsystems.
    - Provide a root endpoint with basic API information.

Workflow:
    Phase 1 — Application startup: initialise logging and memory systems.
    Phase 2 — Register middleware and routers.
    Phase 3 — Serve incoming requests through registered routes.
    Phase 4 — Application shutdown: gracefully close memory connections.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from config.settings import settings
from config.logging_config import setup_logging
from memory.memory_manager import memory_manager
from api.routes import query, ingest, audit, health
from api.middleware import RequestLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and shutdown lifecycle events.

    On startup: initialises logging and verifies memory subsystem
    connectivity. On shutdown: gracefully closes all memory connections.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control back to FastAPI to serve requests during the app's lifetime.
    """
    # ── Startup ───────────────────────────────────────────────────────────
    setup_logging()
    logger.info(
        "Starting {} | environment='{}'",
        settings.app_name,
        settings.environment,
    )

    health_status = memory_manager.health_check()
    logger.info(
        "Startup health check | status='{}'",
        health_status.get("status", "unknown"),
    )

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("Shutting down {}...", settings.app_name)
    memory_manager.close()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance.

    Registers all middleware, routers, and exception handlers required
    for the Institutional Memory System API.

    Returns:
        A fully configured FastAPI application instance.
    """
    app = FastAPI(
        title=settings.app_name,
        description=(
            "Corporate Institutional Memory System — a multi-agent "
            "AI system for capturing, retrieving, and auditing "
            "organisational knowledge."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS Middleware ───────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.environment == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Custom Request Logging Middleware ────────────────────────────────
    app.add_middleware(RequestLoggingMiddleware)

    # ── Register Routers ──────────────────────────────────────────────────
    api_prefix = f"/api/{settings.api.api_version}"

    app.include_router(
        query.router, prefix=f"{api_prefix}/query", tags=["Query"]
    )
    app.include_router(
        ingest.router, prefix=f"{api_prefix}/ingest", tags=["Ingest"]
    )
    app.include_router(
        audit.router, prefix=f"{api_prefix}/audit", tags=["Audit"]
    )
    app.include_router(
        health.router, prefix=f"{api_prefix}/health", tags=["Health"]
    )

    # ── Global Exception Handler ─────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Catches all unhandled exceptions and returns a safe JSON response.

        Args:
            request: The incoming FastAPI request.
            exc: The unhandled exception raised during request processing.

        Returns:
            A JSONResponse with a 500 status and generic error message.
        """
        logger.error(
            "Unhandled exception | path='{}' | error={}",
            request.url.path,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error.",
                "detail": str(exc) if settings.api.debug else None,
            },
        )

    # ── Root Endpoint ─────────────────────────────────────────────────────
    @app.get("/", tags=["Root"])
    async def root() -> dict:
        """Returns basic API information and available endpoints.

        Returns:
            Dictionary with app name, version, and documentation links.
        """
        return {
            "app_name": settings.app_name,
            "version": "1.0.0",
            "environment": settings.environment,
            "docs": "/docs",
            "api_prefix": api_prefix,
        }

    return app


# ── Application Instance ─────────────────────────────────────────────────────
# Uvicorn imports this instance: uvicorn api.main:app

app = create_app()


if __name__ == "__main__":
    """Allows running the API directly via: python -m api.main"""
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.debug,
    )