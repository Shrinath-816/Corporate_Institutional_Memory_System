"""
Module: api/routes/ingest.py

Purpose:
    Defines FastAPI routes for ingesting new knowledge into the
    Institutional Memory System — both bulk email ingestion and
    single-item knowledge capture (meetings, post-mortems, tribal knowledge).

Responsibilities:
    - Accept capture requests for meetings, post-mortems, and tribal knowledge.
    - Delegate capture processing to the MasterOrchestrator.
    - Trigger the bulk email ingestion pipeline on demand.
    - Return structured responses for both capture types.

Workflow:
    Phase 1 — Receive capture or bulk ingestion request from client.
    Phase 2 — Delegate to MasterOrchestrator (capture) or run pipeline (bulk).
    Phase 3 — Return structured response with storage confirmation.
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from loguru import logger
from pydantic import BaseModel, Field

from api.dependencies import get_master_orchestrator, get_request_id
from orchestrators.master_orchestrator import (
    MasterOrchestrator,
    MasterRequest,
    RequestType,
)
from orchestrators.capture_orchestrator import CaptureRequest, ContentType
from agents.capture.tribal_knowledge_agent import ExpertProfile
from schemas.query_schema import QueryResponse
from pydantic import BaseModel


router = APIRouter()


# ── Response Models ──────────────────────────────────────────────────────────

class CaptureEndpointResponse(BaseModel):
    """Response model for the capture endpoint."""

    request_id: str = Field(..., description="Unique request identifier")
    success: bool = Field(..., description="Whether capture succeeded")
    agent_used: str = Field(..., description="Capture agent that processed content")
    summary: str = Field(..., description="Summary of captured knowledge")
    items_captured: int = Field(..., description="Number of items captured")
    stored_in_graph: bool = Field(..., description="Whether stored in Neo4j")
    stored_in_vector: bool = Field(..., description="Whether stored in ChromaDB")
    processing_time_ms: float = Field(..., description="Processing time in ms")
    error: Optional[str] = Field(None, description="Error message if failed")


class BulkIngestionResponse(BaseModel):
    """Response model for the bulk email ingestion endpoint."""

    request_id: str = Field(..., description="Unique request identifier")
    status: str = Field(..., description="STARTED — pipeline runs in background")
    message: str = Field(..., description="Human-readable status message")


class BulkIngestionRequest(BaseModel):
    """Request model for triggering bulk email ingestion."""

    csv_path: Optional[str] = Field(
        None, description="Override path to raw emails CSV"
    )
    max_emails: Optional[int] = Field(
        None, ge=1, description="Override maximum emails to ingest"
    )


# ── Capture Endpoint ──────────────────────────────────────────────────────────

@router.post(
    "/capture",
    response_model=CaptureEndpointResponse,
    summary="Capture a single knowledge item",
)
async def capture_knowledge(
    payload: CaptureRequest,
    orchestrator: MasterOrchestrator = Depends(get_master_orchestrator),
    request_id: str = Depends(get_request_id),
) -> CaptureEndpointResponse:
    """Captures a single knowledge item into the institutional memory.

    Supports three content types: meeting transcripts, post-mortem
    reports, and tribal knowledge interviews. Routes to the appropriate
    capture agent via the Master Orchestrator.

    Args:
        payload: Validated CaptureRequest with content and content_type.
        orchestrator: Injected MasterOrchestrator singleton.
        request_id: Injected request ID from middleware for tracing.

    Returns:
        A CaptureEndpointResponse confirming what was captured and stored.

    Raises:
        HTTPException: 400 if content_type is TRIBAL_KNOWLEDGE without
            an expert_profile. 500 if capture processing fails.
    """
    logger.info(
        "Ingest capture endpoint | request_id='{}' | type='{}'",
        request_id,
        payload.content_type.value,
    )

    if (
        payload.content_type == ContentType.TRIBAL_KNOWLEDGE
        and not payload.expert_profile
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "expert_profile is required when content_type is "
                "'tribal_knowledge'."
            ),
        )

    start = time.perf_counter()

    master_request = MasterRequest(
        request_id=request_id,
        request_type=RequestType.CAPTURE,
        session_id=payload.session_id,
        capture_request=payload,
    )

    response = orchestrator.process(master_request)

    processing_time_ms = round((time.perf_counter() - start) * 1000, 2)

    if not response.capture_result:
        logger.error(
            "Capture processing failed | request_id='{}' | error='{}'",
            request_id,
            response.error,
        )
        raise HTTPException(
            status_code=500,
            detail=response.error or "Capture processing failed.",
        )

    result = response.capture_result

    logger.info(
        "Ingest capture complete | request_id='{}' | success={} | "
        "items={} | time={}ms",
        request_id,
        result.success,
        result.items_captured,
        processing_time_ms,
    )

    return CaptureEndpointResponse(
        request_id=request_id,
        success=result.success,
        agent_used=result.agent_used,
        summary=result.summary,
        items_captured=result.items_captured,
        stored_in_graph=result.stored_in_graph,
        stored_in_vector=result.stored_in_vector,
        processing_time_ms=processing_time_ms,
        error=result.error,
    )


# ── Bulk Email Ingestion Endpoint ─────────────────────────────────────────────

def _run_bulk_ingestion_task(
    csv_path: Optional[str],
    max_emails: Optional[int],
    request_id: str,
) -> None:
    """Background task that runs the full email ingestion pipeline.

    Executed asynchronously via FastAPI BackgroundTasks so the client
    receives an immediate response while ingestion runs in the background.

    Args:
        csv_path: Optional override path to the raw emails CSV.
        max_emails: Optional override for maximum emails to ingest.
        request_id: Request ID for tracing this ingestion run in logs.
    """
    from ingestion.pipeline import run_ingestion_pipeline

    logger.info(
        "Background bulk ingestion started | request_id='{}'", request_id
    )

    try:
        result = run_ingestion_pipeline(
            csv_path=csv_path,
            max_emails=max_emails,
        )
        logger.info(
            "Background bulk ingestion complete | request_id='{}' | "
            "success={} | stored={}",
            request_id,
            result.success,
            result.chunks_stored,
        )
    except Exception as exc:
        logger.error(
            "Background bulk ingestion failed | request_id='{}': {}",
            request_id,
            exc,
        )


@router.post(
    "/bulk",
    response_model=BulkIngestionResponse,
    summary="Trigger bulk email ingestion pipeline",
)
async def trigger_bulk_ingestion(
    payload: BulkIngestionRequest,
    background_tasks: BackgroundTasks,
    request_id: str = Depends(get_request_id),
) -> BulkIngestionResponse:
    """Triggers the full email ingestion pipeline as a background task.

    Runs parse → chunk → embed → store asynchronously so the client
    does not block waiting for potentially long-running ingestion.

    Args:
        payload: BulkIngestionRequest with optional path/limit overrides.
        background_tasks: FastAPI BackgroundTasks for async execution.
        request_id: Injected request ID from middleware for tracing.

    Returns:
        A BulkIngestionResponse confirming the pipeline has started.
    """
    logger.info(
        "Bulk ingestion trigger | request_id='{}' | csv_path='{}' | "
        "max_emails={}",
        request_id,
        payload.csv_path or "default",
        payload.max_emails or "default",
    )

    background_tasks.add_task(
        _run_bulk_ingestion_task,
        payload.csv_path,
        payload.max_emails,
        request_id,
    )

    return BulkIngestionResponse(
        request_id=request_id,
        status="STARTED",
        message=(
            "Bulk ingestion pipeline started in background. "
            "Check server logs or /api/v1/health for collection status."
        ),
    )