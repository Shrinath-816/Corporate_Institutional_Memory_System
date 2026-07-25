"""
Module: api/dependencies.py

Purpose:
    Defines FastAPI dependency injection functions shared across all
    API route modules in the Institutional Memory System.

Responsibilities:
    - Provide the shared MasterOrchestrator instance to route handlers.
    - Extract the request ID attached by RequestLoggingMiddleware.
    - Provide the shared MemoryManager instance for health checks.
    - Centralise dependency construction to avoid duplication across routes.

Workflow:
    FastAPI calls each dependency function automatically when a route
    handler declares it as a parameter via Depends().
"""

from fastapi import Request

from memory.memory_manager import memory_manager, MemoryManager
from orchestrators.master_orchestrator import (
    master_orchestrator,
    MasterOrchestrator,
)


def get_master_orchestrator() -> MasterOrchestrator:
    """Provides the shared MasterOrchestrator singleton to route handlers.

    Used via FastAPI's Depends() in route function signatures to inject
    the orchestrator without each route constructing its own instance.

    Returns:
        The module-level MasterOrchestrator singleton instance.
    """
    return master_orchestrator


def get_memory_manager() -> MemoryManager:
    """Provides the shared MemoryManager singleton to route handlers.

    Used primarily by the health check route to query subsystem status
    directly without going through the full orchestrator stack.

    Returns:
        The module-level MemoryManager singleton instance.
    """
    return memory_manager


def get_request_id(request: Request) -> str:
    """Extracts the request ID attached by RequestLoggingMiddleware.

    Falls back to 'unknown' if the middleware did not run or the
    request state was not populated for any reason.

    Args:
        request: The incoming FastAPI Request object.

    Returns:
        The unique request ID string for this request.
    """
    return getattr(request.state, "request_id", "unknown")