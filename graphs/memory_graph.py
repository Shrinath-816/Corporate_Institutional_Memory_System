"""
Module: graphs/memory_graph.py

Purpose:
    Constructs and compiles all LangGraph state machines for the
    Institutional Memory System.

Responsibilities:
    - Build the Retrieval, Capture, Audit, and Master LangGraph graphs.
    - Register all nodes and conditional edges defined in nodes.py
      and edges.py.
    - Compile each graph into a runnable LangGraph application.
    - Provide clean invoke functions for each graph workflow.
    - Expose compiled graphs as module-level singletons.

Workflow:
    Each graph follows: START → nodes → conditional edges → END
    Compiled graphs are invoked by the API layer and Streamlit UI.
"""

from langgraph.graph import StateGraph, START, END
from loguru import logger

from graphs.states import (
    RetrievalState,
    CaptureState,
    AuditState,
    MasterState,
    create_retrieval_state,
    create_capture_state,
    create_audit_state,
    create_master_state,
)
from graphs.nodes import (
    # Retrieval nodes
    node_classify_query,
    node_retrieve_decision,
    node_retrieve_people,
    node_retrieve_policy,
    node_retrieve_project,
    node_retrieve_competitive,
    node_retrieve_unknown,
    node_apply_fallback,
    node_retrieval_respond,
    # Capture nodes
    node_validate_capture_input,
    node_capture_meeting,
    node_capture_postmortem,
    node_capture_tribal,
    node_capture_respond,
    # Audit nodes
    node_initialise_audit,
    node_run_gap_scan,
    node_run_staleness_scan,
    node_run_spf_scan,
    node_aggregate_audit,
    node_audit_respond,
    # Master nodes
    node_master_receive,
    node_master_route_query,
    node_master_route_capture,
    node_master_route_audit,
    node_master_respond,
)
from graphs.edges import (
    # Retrieval edges
    edge_route_by_category,
    edge_check_fallback_needed,
    # Capture edges
    edge_route_capture_by_type,
    # Audit edges
    edge_route_audit_scan,
    edge_after_gap_scan,
    edge_after_staleness_scan,
    # Master edges
    edge_route_master_by_type,
    edge_after_master_route,
)
from schemas.agent_schema import AgentOutput
from orchestrators.capture_orchestrator import CaptureResult
from orchestrators.audit_orchestrator import AuditReport


# ════════════════════════════════════════════════════════════════════════════
# RETRIEVAL GRAPH
# ════════════════════════════════════════════════════════════════════════════

def _build_retrieval_graph() -> StateGraph:
    """Constructs and compiles the retrieval LangGraph state machine.

    Graph flow:
        START
          → classify_query
          → [edge_route_by_category]
          → retrieve_decision | retrieve_people | retrieve_policy |
            retrieve_project | retrieve_competitive | retrieve_unknown
          → [edge_check_fallback_needed]
          → apply_fallback (optional)
          → retrieval_respond
          → END

    Returns:
        A compiled LangGraph application for retrieval workflows.
    """
    graph = StateGraph(RetrievalState)

    # ── Register nodes ────────────────────────────────────────────────────
    graph.add_node("classify_query", node_classify_query)
    graph.add_node("retrieve_decision", node_retrieve_decision)
    graph.add_node("retrieve_people", node_retrieve_people)
    graph.add_node("retrieve_policy", node_retrieve_policy)
    graph.add_node("retrieve_project", node_retrieve_project)
    graph.add_node("retrieve_competitive", node_retrieve_competitive)
    graph.add_node("retrieve_unknown", node_retrieve_unknown)
    graph.add_node("apply_fallback", node_apply_fallback)
    graph.add_node("retrieval_respond", node_retrieval_respond)

    # ── Entry edge ────────────────────────────────────────────────────────
    graph.add_edge(START, "classify_query")

    # ── Conditional routing after classification ──────────────────────────
    graph.add_conditional_edges(
        "classify_query",
        edge_route_by_category,
        {
            "retrieve_decision": "retrieve_decision",
            "retrieve_people": "retrieve_people",
            "retrieve_policy": "retrieve_policy",
            "retrieve_project": "retrieve_project",
            "retrieve_competitive": "retrieve_competitive",
            "retrieve_unknown": "retrieve_unknown",
            "retrieval_respond": "retrieval_respond",
        },
    )

    # ── Conditional fallback check after each retrieval node ──────────────
    for retrieval_node in [
        "retrieve_decision",
        "retrieve_people",
        "retrieve_policy",
        "retrieve_project",
        "retrieve_competitive",
        "retrieve_unknown",
    ]:
        graph.add_conditional_edges(
            retrieval_node,
            edge_check_fallback_needed,
            {
                "apply_fallback": "apply_fallback",
                "retrieval_respond": "retrieval_respond",
            },
        )

    # ── Fallback → respond ────────────────────────────────────────────────
    graph.add_edge("apply_fallback", "retrieval_respond")

    # ── Terminal edge ─────────────────────────────────────────────────────
    graph.add_edge("retrieval_respond", END)

    return graph


# ════════════════════════════════════════════════════════════════════════════
# CAPTURE GRAPH
# ════════════════════════════════════════════════════════════════════════════

def _build_capture_graph() -> StateGraph:
    """Constructs and compiles the capture LangGraph state machine.

    Graph flow:
        START
          → validate_capture_input
          → [edge_route_capture_by_type]
          → capture_meeting | capture_postmortem | capture_tribal
          → capture_respond
          → END

    Returns:
        A compiled LangGraph application for capture workflows.
    """
    graph = StateGraph(CaptureState)

    # ── Register nodes ────────────────────────────────────────────────────
    graph.add_node("validate_capture_input", node_validate_capture_input)
    graph.add_node("capture_meeting", node_capture_meeting)
    graph.add_node("capture_postmortem", node_capture_postmortem)
    graph.add_node("capture_tribal", node_capture_tribal)
    graph.add_node("capture_respond", node_capture_respond)

    # ── Entry edge ────────────────────────────────────────────────────────
    graph.add_edge(START, "validate_capture_input")

    # ── Conditional routing after validation ──────────────────────────────
    graph.add_conditional_edges(
        "validate_capture_input",
        edge_route_capture_by_type,
        {
            "capture_meeting": "capture_meeting",
            "capture_postmortem": "capture_postmortem",
            "capture_tribal": "capture_tribal",
            "capture_respond": "capture_respond",
        },
    )

    # ── Each capture node → respond ───────────────────────────────────────
    for capture_node in [
        "capture_meeting",
        "capture_postmortem",
        "capture_tribal",
    ]:
        graph.add_edge(capture_node, "capture_respond")

    # ── Terminal edge ─────────────────────────────────────────────────────
    graph.add_edge("capture_respond", END)

    return graph


# ════════════════════════════════════════════════════════════════════════════
# AUDIT GRAPH
# ════════════════════════════════════════════════════════════════════════════

def _build_audit_graph() -> StateGraph:
    """Constructs and compiles the audit LangGraph state machine.

    Graph flow:
        START
          → initialise_audit
          → [edge_route_audit_scan]
          → run_gap_scan → [edge_after_gap_scan]
          → run_staleness_scan → [edge_after_staleness_scan]
          → run_spf_scan
          → aggregate_audit
          → audit_respond
          → END

    Returns:
        A compiled LangGraph application for audit workflows.
    """
    graph = StateGraph(AuditState)

    # ── Register nodes ────────────────────────────────────────────────────
    graph.add_node("initialise_audit", node_initialise_audit)
    graph.add_node("run_gap_scan", node_run_gap_scan)
    graph.add_node("run_staleness_scan", node_run_staleness_scan)
    graph.add_node("run_spf_scan", node_run_spf_scan)
    graph.add_node("aggregate_audit", node_aggregate_audit)
    graph.add_node("audit_respond", node_audit_respond)

    # ── Entry edge ────────────────────────────────────────────────────────
    graph.add_edge(START, "initialise_audit")

    # ── Conditional routing after initialisation ──────────────────────────
    graph.add_conditional_edges(
        "initialise_audit",
        edge_route_audit_scan,
        {
            "run_gap_scan": "run_gap_scan",
            "run_staleness_scan": "run_staleness_scan",
            "run_spf_scan": "run_spf_scan",
            "aggregate_audit": "aggregate_audit",
            "audit_respond": "audit_respond",
        },
    )

    # ── Conditional routing after gap scan ────────────────────────────────
    graph.add_conditional_edges(
        "run_gap_scan",
        edge_after_gap_scan,
        {
            "run_staleness_scan": "run_staleness_scan",
            "run_spf_scan": "run_spf_scan",
            "aggregate_audit": "aggregate_audit",
            "audit_respond": "audit_respond",
        },
    )

    # ── Conditional routing after staleness scan ──────────────────────────
    graph.add_conditional_edges(
        "run_staleness_scan",
        edge_after_staleness_scan,
        {
            "run_spf_scan": "run_spf_scan",
            "aggregate_audit": "aggregate_audit",
            "audit_respond": "audit_respond",
        },
    )

    # ── SPF scan → aggregate ──────────────────────────────────────────────
    graph.add_edge("run_spf_scan", "aggregate_audit")

    # ── Aggregate → respond ───────────────────────────────────────────────
    graph.add_edge("aggregate_audit", "audit_respond")

    # ── Terminal edge ─────────────────────────────────────────────────────
    graph.add_edge("audit_respond", END)

    return graph


# ════════════════════════════════════════════════════════════════════════════
# MASTER GRAPH
# ════════════════════════════════════════════════════════════════════════════

def _build_master_graph() -> StateGraph:
    """Constructs and compiles the master LangGraph state machine.

    Graph flow:
        START
          → master_receive
          → [edge_route_master_by_type]
          → master_route_query | master_route_capture | master_route_audit
          → [edge_after_master_route]
          → master_respond
          → END

    Returns:
        A compiled LangGraph application for master routing workflows.
    """
    graph = StateGraph(MasterState)

    # ── Register nodes ────────────────────────────────────────────────────
    graph.add_node("master_receive", node_master_receive)
    graph.add_node("master_route_query", node_master_route_query)
    graph.add_node("master_route_capture", node_master_route_capture)
    graph.add_node("master_route_audit", node_master_route_audit)
    graph.add_node("master_respond", node_master_respond)

    # ── Entry edge ────────────────────────────────────────────────────────
    graph.add_edge(START, "master_receive")

    # ── Conditional routing after receive ─────────────────────────────────
    graph.add_conditional_edges(
        "master_receive",
        edge_route_master_by_type,
        {
            "master_route_query": "master_route_query",
            "master_route_capture": "master_route_capture",
            "master_route_audit": "master_route_audit",
            "master_respond": "master_respond",
        },
    )

    # ── Each route node → respond via conditional edge ────────────────────
    for route_node in [
        "master_route_query",
        "master_route_capture",
        "master_route_audit",
    ]:
        graph.add_conditional_edges(
            route_node,
            edge_after_master_route,
            {"master_respond": "master_respond"},
        )

    # ── Terminal edge ─────────────────────────────────────────────────────
    graph.add_edge("master_respond", END)

    return graph


# ════════════════════════════════════════════════════════════════════════════
# COMPILED GRAPH SINGLETONS
# ════════════════════════════════════════════════════════════════════════════

logger.info("Compiling LangGraph state machines...")

retrieval_graph = _build_retrieval_graph().compile()
capture_graph = _build_capture_graph().compile()
audit_graph = _build_audit_graph().compile()
master_graph = _build_master_graph().compile()

logger.info("All LangGraph state machines compiled successfully.")


# ════════════════════════════════════════════════════════════════════════════
# GRAPH INVOKE FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def invoke_retrieval(
    query: str,
    session_id: str = None,
    top_k: int = 5,
    metadata_filter: dict = None,
) -> AgentOutput:
    """Invokes the retrieval graph for a user query.

    Args:
        query: The user's natural language query string.
        session_id: Optional session ID for context tracking.
        top_k: Number of documents to retrieve.
        metadata_filter: Optional ChromaDB metadata filter.

    Returns:
        The final AgentOutput from the retrieval graph.

    Raises:
        RuntimeError: If the graph produces no agent output.
    """
    logger.info(
        "invoke_retrieval | query='{}'", query[:60]
    )

    initial_state = create_retrieval_state(
        query=query,
        session_id=session_id,
        top_k=top_k,
        metadata_filter=metadata_filter,
    )

    final_state = retrieval_graph.invoke(initial_state)

    agent_output = final_state.get("agent_output")

    if not agent_output:
        raise RuntimeError(
            "Retrieval graph completed without producing an agent output."
        )

    logger.info(
        "invoke_retrieval complete | agent='{}' | confidence={}",
        agent_output.agent_name,
        agent_output.confidence,
    )

    return agent_output


def invoke_capture(
    content: str,
    content_type: str,
    expert_profile: dict = None,
    session_id: str = None,
) -> CaptureResult:
    """Invokes the capture graph to store new knowledge.

    Args:
        content: Raw content to capture into institutional memory.
        content_type: Type of content being captured.
        expert_profile: Optional expert profile for tribal knowledge.
        session_id: Optional session ID for tracing.

    Returns:
        The CaptureResult from the capture graph.

    Raises:
        RuntimeError: If the graph produces no capture result.
    """
    logger.info(
        "invoke_capture | type='{}' | content_length={}",
        content_type,
        len(content),
    )

    initial_state = create_capture_state(
        content=content,
        content_type=content_type,
        expert_profile=expert_profile,
        session_id=session_id,
    )

    final_state = capture_graph.invoke(initial_state)

    capture_result = final_state.get("capture_result")

    if not capture_result:
        raise RuntimeError(
            "Capture graph completed without producing a capture result."
        )

    logger.info(
        "invoke_capture complete | success={} | items={}",
        capture_result.success,
        capture_result.items_captured,
    )

    return capture_result


def invoke_audit(
    scope: str = "full",
    session_id: str = None,
    generate_summary: bool = True,
) -> AuditReport:
    """Invokes the audit graph to scan institutional memory.

    Args:
        scope: Audit scope string from AuditScope enum values.
        session_id: Optional session ID for tracing.
        generate_summary: Whether to generate LLM executive summary.

    Returns:
        The AuditReport from the audit graph.

    Raises:
        RuntimeError: If the graph produces no audit report.
    """
    logger.info("invoke_audit | scope='{}'", scope)

    initial_state = create_audit_state(
        scope=scope,
        session_id=session_id,
        generate_summary=generate_summary,
    )

    final_state = audit_graph.invoke(initial_state)

    audit_report = final_state.get("audit_report")

    if not audit_report:
        raise RuntimeError(
            "Audit graph completed without producing an audit report."
        )

    logger.info(
        "invoke_audit complete | health='{}' | findings={}",
        audit_report.overall_health,
        audit_report.total_findings,
    )

    return audit_report


def invoke_master(
    request_type: str,
    raw_input: dict,
    session_id: str = None,
) -> dict:
    """Invokes the master graph for any request type.

    Args:
        request_type: Type of request: query, capture, audit, or health.
        raw_input: Raw input payload dictionary for the request.
        session_id: Optional session ID for tracing.

    Returns:
        The final_response dictionary from the master graph state.

    Raises:
        RuntimeError: If the graph produces no final response.
    """
    import uuid

    request_id = uuid.uuid4().hex[:12]

    logger.info(
        "invoke_master | type='{}' | id='{}'",
        request_type,
        request_id,
    )

    initial_state = create_master_state(
        request_id=request_id,
        request_type=request_type,
        raw_input=raw_input,
        session_id=session_id,
    )

    final_state = master_graph.invoke(initial_state)

    final_response = final_state.get("final_response")

    if not final_response:
        raise RuntimeError(
            "Master graph completed without producing a final response."
        )

    logger.info(
        "invoke_master complete | success={} | time={}ms",
        final_state.get("success"),
        final_state.get("processing_time_ms"),
    )

    return final_response