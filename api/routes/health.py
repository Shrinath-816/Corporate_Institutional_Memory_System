"""
Module: api/routes/health.py

Purpose:
    Defines the FastAPI route for checking the health status of the
    Institutional Memory System and all its subsystem dependencies.

Responsibilities:
    - Aggregate health status from ChromaDB, Neo4j, and the query cache.
    - Return a standardised HealthResponse for uptime monitoring tools.
    - Provide a lightweight liveness check separate from the full
      dependency health check.

Workflow:
    Phase 1 — Receive health check request.
    Phase 2 — Query MemoryManager for aggregated subsystem status.
    Phase 3 — Translate raw health data into a structured HealthResponse.
    Phase 4 — Return response with appropriate HTTP status code.
"""

from fastapi import APIRouter, Depends, Response, status
from loguru import logger

from api.dependencies import get_memory_manager, get_request_id
from config.settings import settings
from memory.memory_manager import MemoryManager
from schemas.query_schema import HealthResponse


router = APIRouter()


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Full system health check",
)
async def health_check(
    response: Response,
    memory: MemoryManager = Depends(get_memory_manager),
    request_id: str = Depends(get_request_id),
) -> HealthResponse:
    """Performs a full health check across all memory subsystems.

    Checks ChromaDB, Neo4j, and the in-memory query cache. Sets the
    HTTP status code to 503 if any subsystem is unhealthy, allowing
    load balancers and monitoring tools to detect degraded state.

    Args:
        response: FastAPI Response object for setting status code.
        memory: Injected MemoryManager singleton.
        request_id: Injected request ID from middleware for tracing.

    Returns:
        A HealthResponse with overall status and per-subsystem details.
    """
    logger.info("Health check endpoint | request_id='{}'", request_id)

    health_data = memory.health_check()

    overall_status = health_data.get("status", "unknown")

    # Set HTTP status code based on health — enables load balancer checks
    if overall_status == "healthy":
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    subsystems = health_data.get("subsystems", {})

    dependencies = {
        name: sub_status.get("status", "unknown")
        for name, sub_status in subsystems.items()
    }

    logger.info(
        "Health check complete | request_id='{}' | status='{}' | "
        "dependencies={}",
        request_id,
        overall_status,
        dependencies,
    )

    return HealthResponse(
        status=overall_status,
        version="1.0.0",
        dependencies=dependencies,
    )


@router.get(
    "/live",
    summary="Lightweight liveness check",
)
async def liveness_check() -> dict:
    """Performs a minimal liveness check without querying subsystems.

    Used by container orchestrators (Kubernetes, Docker) for fast
    liveness probes that should not depend on external services like
    Neo4j or ChromaDB being available.

    Returns:
        A simple dictionary confirming the API process is running.
    """
    return {
        "status": "alive",
        "app_name": settings.app_name,
    }