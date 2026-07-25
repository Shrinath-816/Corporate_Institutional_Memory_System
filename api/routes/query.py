"""
Module: api/routes/query.py

Purpose:
    Defines the FastAPI route for submitting natural language queries
    to the Institutional Memory System's retrieval pipeline.

Responsibilities:
    - Accept validated QueryRequest payloads from clients.
    - Delegate query processing to the MasterOrchestrator.
    - Return a structured QueryResponse with answer and sources.
    - Handle and translate orchestrator errors into HTTP responses.

Workflow:
    Phase 1 — Receive and validate QueryRequest from the client.
    Phase 2 — Build a MasterRequest and delegate to MasterOrchestrator.
    Phase 3 — Translate the MasterResponse into a QueryResponse.
    Phase 4 — Return the response or raise an appropriate HTTPException.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from api.dependencies import get_master_orchestrator, get_request_id
from orchestrators.master_orchestrator import (
    MasterOrchestrator,
    MasterRequest,
    RequestType,
)
from schemas.query_schema import QueryRequest, QueryResponse


router = APIRouter()


@router.post("/", response_model=QueryResponse, summary="Submit a query")
async def ask_query(
    payload: QueryRequest,
    orchestrator: MasterOrchestrator = Depends(get_master_orchestrator),
    request_id: str = Depends(get_request_id),
) -> QueryResponse:
    """Submits a natural language query to the institutional memory system.

    Routes the query through the Master Orchestrator, which classifies
    the query, dispatches it to the correct specialist agent, and
    returns a grounded answer with sources.

    Args:
        payload: Validated QueryRequest containing the query string,
            optional session ID, top_k, and category hint.
        orchestrator: Injected MasterOrchestrator singleton.
        request_id: Injected request ID from middleware for tracing.

    Returns:
        A QueryResponse containing the answer, sources, and timing.

    Raises:
        HTTPException: 500 if the orchestrator fails to process the query.
    """
    logger.info(
        "Query endpoint | request_id='{}' | query='{}'",
        request_id,
        payload.query[:80],
    )

    start = time.perf_counter()

    master_request = MasterRequest(
        request_id=request_id,
        request_type=RequestType.QUERY,
        session_id=payload.session_id,
        query=payload.query,
        top_k=payload.top_k,
        category_hint=payload.category_hint,
    )

    response = orchestrator.process(master_request)

    if not response.success or not response.query_result:
        logger.error(
            "Query processing failed | request_id='{}' | error='{}'",
            request_id,
            response.error,
        )
        raise HTTPException(
            status_code=500,
            detail=response.error or "Query processing failed.",
        )

    processing_time_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(
        "Query endpoint complete | request_id='{}' | agent='{}' | "
        "confidence={} | time={}ms",
        request_id,
        response.query_result.agent_name,
        response.query_result.confidence,
        processing_time_ms,
    )

    return QueryResponse(
        request_id=request_id,
        query=payload.query,
        result=response.query_result,
        processing_time_ms=processing_time_ms,
    )