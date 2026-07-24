"""
Module: graphs/edges.py

Purpose:
    Defines all conditional edge functions for the LangGraph state
    machines in the Institutional Memory System.

Responsibilities:
    - Implement every conditional routing function used by LangGraph
      add_conditional_edges() calls.
    - Each edge function receives the current state and returns a
      string node name indicating the next node to execute.
    - Edge functions are pure — they only read state, never mutate it.
    - Provide clear, deterministic routing logic for all graph workflows.

Workflow:
    Edge functions are registered in graphs/memory_graph.py and called
    automatically by LangGraph after each node completes execution.
"""

from loguru import logger

from graphs.states import (
    RetrievalState,
    CaptureState,
    AuditState,
    MasterState,
)
from schemas.agent_schema import QueryCategory


# ════════════════════════════════════════════════════════════════════════════
# RETRIEVAL GRAPH EDGES
# ════════════════════════════════════════════════════════════════════════════

def edge_route_by_category(state: RetrievalState) -> str:
    """Routes to the correct retrieval node based on classified category.

    Called after node_classify_query completes. Checks the is_competitive
    flag first, then routes by QueryCategory, falling back to UNKNOWN.

    Args:
        state: Current RetrievalState with category and flags set.

    Returns:
        Node name string for the next retrieval node to execute.
    """
    # Error during classification → go directly to respond
    if state.get("error"):
        logger.warning(
            "edge_route_by_category: classification error — routing to respond."
        )
        return "retrieval_respond"

    # Competitive queries always go to competitive agent
    if state.get("is_competitive"):
        logger.info(
            "edge_route_by_category: competitive query → retrieve_competitive"
        )
        return "retrieve_competitive"

    category = state.get("category", QueryCategory.UNKNOWN)

    route_map = {
        QueryCategory.DECISION: "retrieve_decision",
        QueryCategory.PEOPLE: "retrieve_people",
        QueryCategory.POLICY: "retrieve_policy",
        QueryCategory.PROJECT: "retrieve_project",
        QueryCategory.UNKNOWN: "retrieve_unknown",
    }

    next_node = route_map.get(category, "retrieve_unknown")

    logger.info(
        "edge_route_by_category: category='{}' → '{}'",
        category,
        next_node,
    )

    return next_node


def edge_check_fallback_needed(state: RetrievalState) -> str:
    """Determines whether fallback retrieval is needed after primary agent.

    Called after any retrieval node completes. Checks agent_output
    confidence against threshold and requires_fallback flag.

    Args:
        state: Current RetrievalState with agent_output populated.

    Returns:
        'apply_fallback' if confidence is low and fallback is available,
        'retrieval_respond' otherwise.
    """
    if state.get("error"):
        logger.warning(
            "edge_check_fallback_needed: error in state — routing to respond."
        )
        return "retrieval_respond"

    agent_output = state.get("agent_output")

    if not agent_output:
        logger.warning(
            "edge_check_fallback_needed: no agent output — routing to respond."
        )
        return "retrieval_respond"

    confidence = agent_output.confidence or 0.0
    requires_fallback = state.get("requires_fallback", False)
    has_fallback = state.get("fallback_category") is not None

    if requires_fallback and has_fallback and confidence < 0.3:
        logger.info(
            "edge_check_fallback_needed: confidence={} < 0.3 "
            "→ apply_fallback",
            confidence,
        )
        return "apply_fallback"

    logger.info(
        "edge_check_fallback_needed: confidence={} — routing to respond.",
        confidence,
    )
    return "retrieval_respond"


# ════════════════════════════════════════════════════════════════════════════
# CAPTURE GRAPH EDGES
# ════════════════════════════════════════════════════════════════════════════

def edge_route_capture_by_type(state: CaptureState) -> str:
    """Routes to the correct capture node based on content type.

    Called after node_validate_capture_input completes. If validation
    failed, routes to capture_respond immediately to surface the error.

    Args:
        state: Current CaptureState with content_type and
            validation_passed set.

    Returns:
        Node name string for the next capture node to execute.
    """
    if not state.get("validation_passed"):
        logger.warning(
            "edge_route_capture_by_type: validation failed — routing to respond."
        )
        return "capture_respond"

    content_type = state.get("content_type", "")

    route_map = {
        "meeting_transcript": "capture_meeting",
        "post_mortem": "capture_postmortem",
        "tribal_knowledge": "capture_tribal",
    }

    next_node = route_map.get(content_type, "capture_respond")

    logger.info(
        "edge_route_capture_by_type: type='{}' → '{}'",
        content_type,
        next_node,
    )

    return next_node


# ════════════════════════════════════════════════════════════════════════════
# AUDIT GRAPH EDGES
# ════════════════════════════════════════════════════════════════════════════

def edge_route_audit_scan(state: AuditState) -> str:
    """Routes to the first enabled audit scan node.

    Called after node_initialise_audit completes. Determines which
    audit scan to run first based on enabled flags and scope.

    Args:
        state: Current AuditState with run_* flags set.

    Returns:
        Node name of the first audit scan to execute.
    """
    if state.get("error"):
        logger.warning(
            "edge_route_audit_scan: error in state — routing to respond."
        )
        return "audit_respond"

    if state.get("run_gap_scan"):
        logger.info("edge_route_audit_scan → run_gap_scan")
        return "run_gap_scan"

    if state.get("run_staleness_scan"):
        logger.info("edge_route_audit_scan → run_staleness_scan")
        return "run_staleness_scan"

    if state.get("run_spf_scan"):
        logger.info("edge_route_audit_scan → run_spf_scan")
        return "run_spf_scan"

    logger.warning("edge_route_audit_scan: no scans enabled — aggregating.")
    return "aggregate_audit"


def edge_after_gap_scan(state: AuditState) -> str:
    """Routes to the next audit node after gap scan completes.

    Args:
        state: Current AuditState after gap scan.

    Returns:
        Next audit node name based on remaining enabled scans.
    """
    if state.get("error"):
        return "audit_respond"

    if state.get("run_staleness_scan"):
        logger.info("edge_after_gap_scan → run_staleness_scan")
        return "run_staleness_scan"

    if state.get("run_spf_scan"):
        logger.info("edge_after_gap_scan → run_spf_scan")
        return "run_spf_scan"

    logger.info("edge_after_gap_scan → aggregate_audit")
    return "aggregate_audit"


def edge_after_staleness_scan(state: AuditState) -> str:
    """Routes to the next audit node after staleness scan completes.

    Args:
        state: Current AuditState after staleness scan.

    Returns:
        Next audit node name based on remaining enabled scans.
    """
    if state.get("error"):
        return "audit_respond"

    if state.get("run_spf_scan"):
        logger.info("edge_after_staleness_scan → run_spf_scan")
        return "run_spf_scan"

    logger.info("edge_after_staleness_scan → aggregate_audit")
    return "aggregate_audit"


# ════════════════════════════════════════════════════════════════════════════
# MASTER GRAPH EDGES
# ════════════════════════════════════════════════════════════════════════════

def edge_route_master_by_type(state: MasterState) -> str:
    """Routes the master graph to the correct sub-graph handler node.

    Called after node_master_receive completes. Routes by request_type
    to the appropriate master route node.

    Args:
        state: Current MasterState with request_type set.

    Returns:
        Node name string for the next master routing node.
    """
    if state.get("error"):
        logger.warning(
            "edge_route_master_by_type: error — routing to master_respond."
        )
        return "master_respond"

    request_type = state.get("request_type", "").lower()

    route_map = {
        "query": "master_route_query",
        "capture": "master_route_capture",
        "audit": "master_route_audit",
        "health": "master_respond",
    }

    next_node = route_map.get(request_type, "master_respond")

    logger.info(
        "edge_route_master_by_type: type='{}' → '{}'",
        request_type,
        next_node,
    )

    return next_node


def edge_after_master_route(state: MasterState) -> str:
    """Routes to master_respond after any master route node completes.

    Called after master_route_query, master_route_capture, or
    master_route_audit completes. Always proceeds to master_respond.

    Args:
        state: Current MasterState after routing.

    Returns:
        Always returns 'master_respond'.
    """
    logger.info(
        "edge_after_master_route: routed_to='{}' → master_respond",
        state.get("routed_to", "unknown"),
    )
    return "master_respond"