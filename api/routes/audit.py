"""
Module: api/routes/audit.py

Purpose:
    Defines FastAPI routes for triggering and retrieving institutional
    memory audit scans — knowledge gaps, staleness, and single points
    of failure.

Responsibilities:
    - Accept audit scan requests with configurable scope.
    - Delegate audit processing to the MasterOrchestrator.
    - Return a structured AuditReport with findings and executive summary.
    - Provide a lightweight endpoint for quick health-style audit checks.

Workflow:
    Phase 1 — Receive AuditEndpointRequest with desired scope.
    Phase 2 — Build a MasterRequest and delegate to MasterOrchestrator.
    Phase 3 — Return the AuditReport or raise an HTTPException on failure.
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from api.dependencies import get_master_orchestrator, get_request_id
from orchestrators.master_orchestrator import (
    MasterOrchestrator,
    MasterRequest,
    RequestType,
)
from orchestrators.audit_orchestrator import AuditReport, AuditScope


router = APIRouter()


# ── Request Model ─────────────────────────────────────────────────────────────

class AuditEndpointRequest(BaseModel):
    """Request model for triggering an audit scan."""

    scope: AuditScope = Field(
        default=AuditScope.FULL,
        description=(
            "Audit scope: full, gaps_only, staleness_only, spf_only, or quick"
        ),
    )
    generate_summary: bool = Field(
        default=True,
        description="Whether to generate an LLM executive summary",
    )


# ── Full Audit Endpoint ──────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=AuditReport,
    summary="Run an institutional memory audit scan",
)
async def run_audit(
    payload: AuditEndpointRequest,
    orchestrator: MasterOrchestrator = Depends(get_master_orchestrator),
    request_id: str = Depends(get_request_id),
) -> AuditReport:
    """Runs an audit scan across the institutional memory system.

    Coordinates gap detection, staleness analysis, and single point of
    failure identification based on the requested scope. Returns a
    comprehensive report with findings and an executive summary.

    Args:
        payload: AuditEndpointRequest specifying scope and summary flag.
        orchestrator: Injected MasterOrchestrator singleton.
        request_id: Injected request ID from middleware for tracing.

    Returns:
        A complete AuditReport with findings, health status, and summary.

    Raises:
        HTTPException: 500 if the audit orchestrator fails to complete.
    """
    logger.info(
        "Audit endpoint | request_id='{}' | scope='{}'",
        request_id,
        payload.scope.value,
    )

    start = time.perf_counter()

    master_request = MasterRequest(
        request_id=request_id,
        request_type=RequestType.AUDIT,
        audit_scope=payload.scope,
        generate_audit_summary=payload.generate_summary,
    )

    response = orchestrator.process(master_request)

    if not response.success or not response.audit_report:
        logger.error(
            "Audit processing failed | request_id='{}' | error='{}'",
            request_id,
            response.error,
        )
        raise HTTPException(
            status_code=500,
            detail=response.error or "Audit processing failed.",
        )

    processing_time_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(
        "Audit endpoint complete | request_id='{}' | health='{}' | "
        "findings={} | critical={} | time={}ms",
        request_id,
        response.audit_report.overall_health,
        response.audit_report.total_findings,
        response.audit_report.critical_findings,
        processing_time_ms,
    )

    return response.audit_report


# ── Quick Audit Endpoint (GET, query params) ─────────────────────────────────

@router.get(
    "/quick",
    response_model=AuditReport,
    summary="Run a quick gap-only audit scan",
)
async def run_quick_audit(
    orchestrator: MasterOrchestrator = Depends(get_master_orchestrator),
    request_id: str = Depends(get_request_id),
    generate_summary: bool = Query(
        default=False,
        description="Whether to generate an LLM executive summary",
    ),
) -> AuditReport:
    """Runs a lightweight, gap-only audit scan for frequent health checks.

    Optimised for speed — skips staleness and single point of failure
    analysis. Intended for dashboard widgets or scheduled monitoring
    where full audit depth is not required.

    Args:
        orchestrator: Injected MasterOrchestrator singleton.
        request_id: Injected request ID from middleware for tracing.
        generate_summary: Whether to generate an LLM summary. Defaults
            to False for speed since this endpoint is meant to be fast.

    Returns:
        An AuditReport scoped to gap detection findings only.

    Raises:
        HTTPException: 500 if the audit orchestrator fails to complete.
    """
    logger.info(
        "Quick audit endpoint | request_id='{}'", request_id
    )

    start = time.perf_counter()

    master_request = MasterRequest(
        request_id=request_id,
        request_type=RequestType.AUDIT,
        audit_scope=AuditScope.QUICK,
        generate_audit_summary=generate_summary,
    )

    response = orchestrator.process(master_request)

    if not response.success or not response.audit_report:
        logger.error(
            "Quick audit failed | request_id='{}' | error='{}'",
            request_id,
            response.error,
        )
        raise HTTPException(
            status_code=500,
            detail=response.error or "Quick audit processing failed.",
        )

    processing_time_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(
        "Quick audit complete | request_id='{}' | health='{}' | time={}ms",
        request_id,
        response.audit_report.overall_health,
        processing_time_ms,
    )

    return response.audit_report