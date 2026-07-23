"""
Module: graphs/states.py

Purpose:
    Defines all LangGraph state TypedDict classes used across the
    Institutional Memory System's graph-based workflows.

Responsibilities:
    - Define the shared state schema passed between LangGraph nodes.
    - Provide typed state for the retrieval, capture, and audit graphs.
    - Ensure all state fields are clearly typed for LangGraph compatibility.
    - Serve as the single source of truth for graph state structure.

Workflow:
    State objects are created at graph entry, mutated by each node,
    and passed forward through the graph until the END node is reached.
"""

from typing import Any, Optional
from typing_extensions import TypedDict, Annotated
import operator

from schemas.agent_schema import AgentOutput, QueryCategory
from orchestrators.capture_orchestrator import CaptureResult
from orchestrators.audit_orchestrator import AuditReport


# ── Retrieval Graph State ────────────────────────────────────────────────────

class RetrievalState(TypedDict):
    """State schema for the retrieval LangGraph workflow.

    Flows through: classify → route → retrieve → (fallback?) → respond

    Attributes:
        query: Original user query string.
        session_id: Optional session identifier.
        top_k: Number of documents to retrieve.
        category: Classified QueryCategory from router node.
        confidence: Router confidence score.
        fallback_category: Optional fallback category if confidence low.
        metadata_filter: Optional ChromaDB metadata filter.
        agent_output: Final AgentOutput produced by specialist agent.
        error: Error message if any node fails.
        requires_fallback: Flag set when primary confidence is too low.
        is_competitive: Flag set when query has competitive signals.
        node_history: List of node names executed in order.
    """

    query: str
    session_id: Optional[str]
    top_k: int
    category: Optional[QueryCategory]
    confidence: Optional[float]
    fallback_category: Optional[QueryCategory]
    metadata_filter: Optional[dict]
    agent_output: Optional[AgentOutput]
    error: Optional[str]
    requires_fallback: bool
    is_competitive: bool
    node_history: Annotated[list[str], operator.add]


# ── Capture Graph State ──────────────────────────────────────────────────────

class CaptureState(TypedDict):
    """State schema for the capture LangGraph workflow.

    Flows through: validate → route → capture → store → respond

    Attributes:
        content: Raw content submitted for capture.
        content_type: Type of content being captured.
        expert_profile: Expert profile for tribal knowledge capture.
        session_id: Optional session identifier.
        capture_result: Result from the capture agent.
        validation_passed: Whether input validation succeeded.
        error: Error message if any node fails.
        node_history: List of node names executed in order.
    """

    content: str
    content_type: str
    expert_profile: Optional[dict]
    session_id: Optional[str]
    capture_result: Optional[CaptureResult]
    validation_passed: bool
    error: Optional[str]
    node_history: Annotated[list[str], operator.add]


# ── Audit Graph State ────────────────────────────────────────────────────────

class AuditState(TypedDict):
    """State schema for the audit LangGraph workflow.

    Flows through: initialise → gap_scan → staleness_scan → spf_scan
                   → aggregate → summarise → respond

    Attributes:
        scope: Audit scope string from AuditScope enum.
        session_id: Optional session identifier.
        run_gap_scan: Whether to run the gap detector agent.
        run_staleness_scan: Whether to run the staleness agent.
        run_spf_scan: Whether to run the SPF agent.
        gap_findings: Raw gap detector findings count.
        staleness_findings: Raw staleness findings count.
        spf_findings: Raw SPF findings count.
        audit_report: Final AuditReport after aggregation.
        generate_summary: Whether to generate LLM executive summary.
        error: Error message if any node fails.
        node_history: List of node names executed in order.
    """

    scope: str
    session_id: Optional[str]
    run_gap_scan: bool
    run_staleness_scan: bool
    run_spf_scan: bool
    gap_findings: int
    staleness_findings: int
    spf_findings: int
    audit_report: Optional[AuditReport]
    generate_summary: bool
    error: Optional[str]
    node_history: Annotated[list[str], operator.add]


# ── Master Graph State ───────────────────────────────────────────────────────

class MasterState(TypedDict):
    """State schema for the top-level master LangGraph workflow.

    The master graph receives all requests, classifies request type,
    and delegates to the appropriate sub-graph.

    Attributes:
        request_id: Unique request identifier.
        request_type: Type of request: QUERY, CAPTURE, AUDIT, HEALTH.
        session_id: Optional session identifier.
        raw_input: Raw input payload as a dictionary.
        routed_to: Name of the sub-graph this request was routed to.
        final_response: Final response payload as a dictionary.
        success: Whether the overall request succeeded.
        error: Error message if processing failed.
        processing_time_ms: Total processing time in milliseconds.
        node_history: List of node names executed in order.
    """

    request_id: str
    request_type: str
    session_id: Optional[str]
    raw_input: dict[str, Any]
    routed_to: Optional[str]
    final_response: Optional[dict[str, Any]]
    success: bool
    error: Optional[str]
    processing_time_ms: float
    node_history: Annotated[list[str], operator.add]


# ── State Factory Functions ───────────────────────────────────────────────────

def create_retrieval_state(
    query: str,
    session_id: Optional[str] = None,
    top_k: int = 5,
    metadata_filter: Optional[dict] = None,
) -> RetrievalState:
    """Creates a default-initialised RetrievalState.

    Args:
        query: The user's query string.
        session_id: Optional session identifier.
        top_k: Number of documents to retrieve.
        metadata_filter: Optional ChromaDB metadata filter.

    Returns:
        A RetrievalState with all fields initialised to defaults.
    """
    return RetrievalState(
        query=query,
        session_id=session_id,
        top_k=top_k,
        category=None,
        confidence=None,
        fallback_category=None,
        metadata_filter=metadata_filter,
        agent_output=None,
        error=None,
        requires_fallback=False,
        is_competitive=False,
        node_history=[],
    )


def create_capture_state(
    content: str,
    content_type: str,
    expert_profile: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> CaptureState:
    """Creates a default-initialised CaptureState.

    Args:
        content: Raw content for capture.
        content_type: Type of content being captured.
        expert_profile: Optional expert profile dict.
        session_id: Optional session identifier.

    Returns:
        A CaptureState with all fields initialised to defaults.
    """
    return CaptureState(
        content=content,
        content_type=content_type,
        expert_profile=expert_profile,
        session_id=session_id,
        capture_result=None,
        validation_passed=False,
        error=None,
        node_history=[],
    )


def create_audit_state(
    scope: str = "full",
    session_id: Optional[str] = None,
    generate_summary: bool = True,
) -> AuditState:
    """Creates a default-initialised AuditState.

    Args:
        scope: Audit scope string from AuditScope enum.
        session_id: Optional session identifier.
        generate_summary: Whether to generate LLM summary.

    Returns:
        An AuditState with all fields initialised to defaults.
    """
    run_all = scope == "full"
    return AuditState(
        scope=scope,
        session_id=session_id,
        run_gap_scan=run_all or scope in {"gaps_only", "quick"},
        run_staleness_scan=run_all or scope == "staleness_only",
        run_spf_scan=run_all or scope == "spf_only",
        gap_findings=0,
        staleness_findings=0,
        spf_findings=0,
        audit_report=None,
        generate_summary=generate_summary,
        error=None,
        node_history=[],
    )


def create_master_state(
    request_id: str,
    request_type: str,
    raw_input: dict[str, Any],
    session_id: Optional[str] = None,
) -> MasterState:
    """Creates a default-initialised MasterState.

    Args:
        request_id: Unique request identifier.
        request_type: Type of request being processed.
        raw_input: Raw input payload dictionary.
        session_id: Optional session identifier.

    Returns:
        A MasterState with all fields initialised to defaults.
    """
    return MasterState(
        request_id=request_id,
        request_type=request_type,
        session_id=session_id,
        raw_input=raw_input,
        routed_to=None,
        final_response=None,
        success=False,
        error=None,
        processing_time_ms=0.0,
        node_history=[],
    )