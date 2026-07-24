"""
Module: graphs/nodes.py

Purpose:
    Defines all LangGraph node functions for the Institutional Memory
    System's retrieval, capture, and audit graph workflows.

Responsibilities:
    - Implement every node function consumed by the LangGraph state machines.
    - Each node receives the current state, performs one unit of work,
      and returns a partial state update dictionary.
    - Nodes are pure functions — no side effects beyond state mutation.
    - All nodes are typed against their respective state TypedDicts.

Workflow:
    Nodes are composed into graphs in graphs/memory_graph.py.
    Each node function signature: (state: XState) -> dict
"""

import time
from typing import Any

from loguru import logger

from graphs.states import (
    RetrievalState,
    CaptureState,
    AuditState,
    MasterState,
)
from orchestrators.master_orchestrator import (
    MasterOrchestrator,
    MasterRequest,
    RequestType,
    master_orchestrator,
)
from orchestrators.retrieval_orchestrator import (
    RetrievalOrchestrator,
    RetrievalRequest,
)
from orchestrators.capture_orchestrator import (
    CaptureOrchestrator,
    CaptureRequest,
    ContentType,
)
from orchestrators.audit_orchestrator import (
    AuditOrchestrator,
    AuditRequest,
    AuditScope,
)
from agents.retrieval.router_agent import RouterAgent
from schemas.agent_schema import QueryCategory, AgentOutput, AgentStatus
from memory.memory_manager import memory_manager


# ── Shared Instances ─────────────────────────────────────────────────────────
# Reuse orchestrator singletons already initialised at import time.

_retrieval_orchestrator = RetrievalOrchestrator(memory=memory_manager)
_capture_orchestrator = CaptureOrchestrator(memory=memory_manager)
_audit_orchestrator = AuditOrchestrator(memory=memory_manager)
_router_agent = RouterAgent(memory=memory_manager)


# ════════════════════════════════════════════════════════════════════════════
# RETRIEVAL GRAPH NODES
# ════════════════════════════════════════════════════════════════════════════

def node_classify_query(state: RetrievalState) -> dict:
    """Node: Classifies the user query using the Router Agent.

    Invokes the RouterAgent to determine the QueryCategory and
    confidence score. Sets the requires_fallback and is_competitive
    flags for downstream edge routing.

    Args:
        state: Current RetrievalState with query populated.

    Returns:
        Partial state update with category, confidence, fallback_category,
        requires_fallback, is_competitive, and node_history.
    """
    logger.info("Node: classify_query | query='{}'", state["query"][:60])

    try:
        router_output = _router_agent.classify(state["query"])

        # Detect competitive intelligence signals
        competitive_signals = [
            "competitor", "competition", "versus", " vs ",
            "rival", "market share", "industry", "benchmark",
        ]
        is_competitive = any(
            signal in state["query"].lower()
            for signal in competitive_signals
        )

        return {
            "category": router_output.category,
            "confidence": router_output.confidence,
            "fallback_category": router_output.fallback_category,
            "requires_fallback": router_output.confidence < 0.75,
            "is_competitive": is_competitive,
            "node_history": ["classify_query"],
        }

    except Exception as exc:
        logger.error("classify_query node failed: {}", exc)
        return {
            "category": QueryCategory.UNKNOWN,
            "confidence": 0.0,
            "fallback_category": None,
            "requires_fallback": False,
            "is_competitive": False,
            "error": str(exc),
            "node_history": ["classify_query"],
        }


def node_retrieve_decision(state: RetrievalState) -> dict:
    """Node: Executes the DecisionAgent for DECISION category queries.

    Args:
        state: Current RetrievalState.

    Returns:
        Partial state update with agent_output and node_history.
    """
    logger.info("Node: retrieve_decision")

    request = RetrievalRequest(
        query=state["query"],
        session_id=state.get("session_id"),
        top_k=state.get("top_k", 5),
        category_hint=QueryCategory.DECISION,
        metadata_filter=state.get("metadata_filter"),
    )

    try:
        output = _retrieval_orchestrator.retrieve(request)
        return {
            "agent_output": output,
            "node_history": ["retrieve_decision"],
        }
    except Exception as exc:
        logger.error("retrieve_decision node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["retrieve_decision"],
        }


def node_retrieve_people(state: RetrievalState) -> dict:
    """Node: Executes the PeopleAgent for PEOPLE category queries.

    Args:
        state: Current RetrievalState.

    Returns:
        Partial state update with agent_output and node_history.
    """
    logger.info("Node: retrieve_people")

    request = RetrievalRequest(
        query=state["query"],
        session_id=state.get("session_id"),
        top_k=state.get("top_k", 5),
        category_hint=QueryCategory.PEOPLE,
        metadata_filter=state.get("metadata_filter"),
    )

    try:
        output = _retrieval_orchestrator.retrieve(request)
        return {
            "agent_output": output,
            "node_history": ["retrieve_people"],
        }
    except Exception as exc:
        logger.error("retrieve_people node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["retrieve_people"],
        }


def node_retrieve_policy(state: RetrievalState) -> dict:
    """Node: Executes the PolicyAgent for POLICY category queries.

    Args:
        state: Current RetrievalState.

    Returns:
        Partial state update with agent_output and node_history.
    """
    logger.info("Node: retrieve_policy")

    request = RetrievalRequest(
        query=state["query"],
        session_id=state.get("session_id"),
        top_k=state.get("top_k", 5),
        category_hint=QueryCategory.POLICY,
        metadata_filter=state.get("metadata_filter"),
    )

    try:
        output = _retrieval_orchestrator.retrieve(request)
        return {
            "agent_output": output,
            "node_history": ["retrieve_policy"],
        }
    except Exception as exc:
        logger.error("retrieve_policy node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["retrieve_people"],
        }


def node_retrieve_project(state: RetrievalState) -> dict:
    """Node: Executes the ProjectAgent for PROJECT category queries.

    Args:
        state: Current RetrievalState.

    Returns:
        Partial state update with agent_output and node_history.
    """
    logger.info("Node: retrieve_project")

    request = RetrievalRequest(
        query=state["query"],
        session_id=state.get("session_id"),
        top_k=state.get("top_k", 5),
        category_hint=QueryCategory.PROJECT,
        metadata_filter=state.get("metadata_filter"),
    )

    try:
        output = _retrieval_orchestrator.retrieve(request)
        return {
            "agent_output": output,
            "node_history": ["retrieve_project"],
        }
    except Exception as exc:
        logger.error("retrieve_project node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["retrieve_project"],
        }


def node_retrieve_competitive(state: RetrievalState) -> dict:
    """Node: Executes the CompetitiveAgent for competitive intelligence queries.

    Args:
        state: Current RetrievalState.

    Returns:
        Partial state update with agent_output and node_history.
    """
    logger.info("Node: retrieve_competitive")

    request = RetrievalRequest(
        query=state["query"],
        session_id=state.get("session_id"),
        top_k=state.get("top_k", 5),
        metadata_filter=state.get("metadata_filter"),
    )

    try:
        output = _retrieval_orchestrator.retrieve(request)
        return {
            "agent_output": output,
            "node_history": ["retrieve_competitive"],
        }
    except Exception as exc:
        logger.error("retrieve_competitive node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["retrieve_competitive"],
        }


def node_retrieve_unknown(state: RetrievalState) -> dict:
    """Node: Runs multi-agent retrieval for UNKNOWN category queries.

    Args:
        state: Current RetrievalState.

    Returns:
        Partial state update with agent_output and node_history.
    """
    logger.info("Node: retrieve_unknown — running multi-agent retrieval.")

    request = RetrievalRequest(
        query=state["query"],
        session_id=state.get("session_id"),
        top_k=state.get("top_k", 5),
        metadata_filter=state.get("metadata_filter"),
    )

    try:
        output = _retrieval_orchestrator.retrieve(request)
        return {
            "agent_output": output,
            "node_history": ["retrieve_unknown"],
        }
    except Exception as exc:
        logger.error("retrieve_unknown node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["retrieve_unknown"],
        }


def node_apply_fallback(state: RetrievalState) -> dict:
    """Node: Attempts fallback retrieval when primary confidence is low.

    Uses the fallback_category from the router to retry with a
    different specialist agent.

    Args:
        state: Current RetrievalState with fallback_category set.

    Returns:
        Partial state update with agent_output and node_history.
    """
    logger.info(
        "Node: apply_fallback | fallback_category='{}'",
        state.get("fallback_category"),
    )

    fallback_category = state.get("fallback_category")

    if not fallback_category or fallback_category == QueryCategory.UNKNOWN:
        logger.debug("No valid fallback category — keeping primary output.")
        return {"node_history": ["apply_fallback"]}

    request = RetrievalRequest(
        query=state["query"],
        session_id=state.get("session_id"),
        top_k=state.get("top_k", 5),
        category_hint=fallback_category,
        metadata_filter=state.get("metadata_filter"),
    )

    try:
        fallback_output = _retrieval_orchestrator.retrieve(request)
        primary_output = state.get("agent_output")

        # Keep whichever output has higher confidence
        if primary_output and (
            fallback_output.confidence or 0.0
        ) > (primary_output.confidence or 0.0):
            return {
                "agent_output": fallback_output,
                "node_history": ["apply_fallback"],
            }

        return {"node_history": ["apply_fallback"]}

    except Exception as exc:
        logger.warning("apply_fallback node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["apply_fallback"],
        }


def node_retrieval_respond(state: RetrievalState) -> dict:
    """Node: Final retrieval node — validates and finalises the agent output.

    If no agent_output exists (all agents failed), creates a graceful
    error response rather than returning None.

    Args:
        state: Current RetrievalState with agent_output populated.

    Returns:
        Partial state update with validated agent_output.
    """
    logger.info("Node: retrieval_respond")

    if not state.get("agent_output"):
        error_output = AgentOutput(
            agent_name="RetrievalGraph",
            query=state["query"],
            answer=(
                "I was unable to find relevant information. "
                "Please try rephrasing your query."
            ),
            sources=[],
            status=AgentStatus.FAILED,
            confidence=0.0,
        )
        return {
            "agent_output": error_output,
            "node_history": ["retrieval_respond"],
        }

    return {"node_history": ["retrieval_respond"]}


# ════════════════════════════════════════════════════════════════════════════
# CAPTURE GRAPH NODES
# ════════════════════════════════════════════════════════════════════════════

def node_validate_capture_input(state: CaptureState) -> dict:
    """Node: Validates capture input before routing to a capture agent.

    Checks that content is non-empty and content_type is valid.
    Sets validation_passed flag for downstream edge routing.

    Args:
        state: Current CaptureState with content and content_type.

    Returns:
        Partial state update with validation_passed and node_history.
    """
    logger.info(
        "Node: validate_capture_input | type='{}'",
        state.get("content_type"),
    )

    content = state.get("content", "")
    content_type = state.get("content_type", "")

    valid_types = {ct.value for ct in ContentType}

    if not content or len(content.strip()) < 20:
        return {
            "validation_passed": False,
            "error": "Content is too short or empty.",
            "node_history": ["validate_capture_input"],
        }

    if content_type not in valid_types:
        return {
            "validation_passed": False,
            "error": f"Invalid content_type: '{content_type}'.",
            "node_history": ["validate_capture_input"],
        }

    return {
        "validation_passed": True,
        "node_history": ["validate_capture_input"],
    }


def node_capture_meeting(state: CaptureState) -> dict:
    """Node: Routes content to MeetingAgent for meeting transcript capture.

    Args:
        state: Current CaptureState with validated content.

    Returns:
        Partial state update with capture_result and node_history.
    """
    logger.info("Node: capture_meeting")

    try:
        request = CaptureRequest(
            content=state["content"],
            content_type=ContentType.MEETING_TRANSCRIPT,
            session_id=state.get("session_id"),
        )
        result = _capture_orchestrator.capture(request)
        return {
            "capture_result": result,
            "node_history": ["capture_meeting"],
        }
    except Exception as exc:
        logger.error("capture_meeting node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["capture_meeting"],
        }


def node_capture_postmortem(state: CaptureState) -> dict:
    """Node: Routes content to PostMortemAgent for post-mortem capture.

    Args:
        state: Current CaptureState with validated content.

    Returns:
        Partial state update with capture_result and node_history.
    """
    logger.info("Node: capture_postmortem")

    try:
        request = CaptureRequest(
            content=state["content"],
            content_type=ContentType.POST_MORTEM,
            session_id=state.get("session_id"),
        )
        result = _capture_orchestrator.capture(request)
        return {
            "capture_result": result,
            "node_history": ["capture_postmortem"],
        }
    except Exception as exc:
        logger.error("capture_postmortem node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["capture_postmortem"],
        }


def node_capture_tribal(state: CaptureState) -> dict:
    """Node: Routes content to TribalKnowledgeAgent for knowledge capture.

    Args:
        state: Current CaptureState with validated content and
            expert_profile populated.

    Returns:
        Partial state update with capture_result and node_history.
    """
    logger.info("Node: capture_tribal")

    from agents.capture.tribal_knowledge_agent import ExpertProfile

    expert_profile = None
    profile_dict = state.get("expert_profile")

    if profile_dict:
        try:
            expert_profile = ExpertProfile(**profile_dict)
        except Exception as exc:
            logger.warning(
                "Failed to parse expert_profile: {}", exc
            )

    try:
        request = CaptureRequest(
            content=state["content"],
            content_type=ContentType.TRIBAL_KNOWLEDGE,
            expert_profile=expert_profile,
            session_id=state.get("session_id"),
        )
        result = _capture_orchestrator.capture(request)
        return {
            "capture_result": result,
            "node_history": ["capture_tribal"],
        }
    except Exception as exc:
        logger.error("capture_tribal node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["capture_tribal"],
        }


def node_capture_respond(state: CaptureState) -> dict:
    """Node: Final capture node — validates and finalises capture result.

    Args:
        state: Current CaptureState with capture_result populated.

    Returns:
        Partial state update confirming completion.
    """
    logger.info(
        "Node: capture_respond | success={}",
        state.get("capture_result") is not None,
    )
    return {"node_history": ["capture_respond"]}


# ════════════════════════════════════════════════════════════════════════════
# AUDIT GRAPH NODES
# ════════════════════════════════════════════════════════════════════════════

def node_initialise_audit(state: AuditState) -> dict:
    """Node: Initialises audit scan flags based on requested scope.

    Args:
        state: Current AuditState with scope populated.

    Returns:
        Partial state update with run_* flags and node_history.
    """
    logger.info(
        "Node: initialise_audit | scope='{}'", state.get("scope")
    )

    scope = state.get("scope", "full")
    run_all = scope == "full"

    return {
        "run_gap_scan": run_all or scope in {"gaps_only", "quick"},
        "run_staleness_scan": run_all or scope == "staleness_only",
        "run_spf_scan": run_all or scope == "spf_only",
        "node_history": ["initialise_audit"],
    }


def node_run_gap_scan(state: AuditState) -> dict:
    """Node: Runs the GapDetectorAgent if gap scanning is enabled.

    Args:
        state: Current AuditState.

    Returns:
        Partial state update with gap_findings count and node_history.
    """
    logger.info("Node: run_gap_scan")

    if not state.get("run_gap_scan"):
        logger.debug("Gap scan skipped by scope.")
        return {"node_history": ["run_gap_scan"]}

    try:
        output = _audit_orchestrator._gap_agent.scan()
        return {
            "gap_findings": output.gaps_found,
            "node_history": ["run_gap_scan"],
        }
    except Exception as exc:
        logger.error("run_gap_scan node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["run_gap_scan"],
        }


def node_run_staleness_scan(state: AuditState) -> dict:
    """Node: Runs the StalenessAgent if staleness scanning is enabled.

    Args:
        state: Current AuditState.

    Returns:
        Partial state update with staleness_findings count and node_history.
    """
    logger.info("Node: run_staleness_scan")

    if not state.get("run_staleness_scan"):
        logger.debug("Staleness scan skipped by scope.")
        return {"node_history": ["run_staleness_scan"]}

    try:
        output = _audit_orchestrator._staleness_agent.scan()
        return {
            "staleness_findings": output.total_findings,
            "node_history": ["run_staleness_scan"],
        }
    except Exception as exc:
        logger.error("run_staleness_scan node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["run_staleness_scan"],
        }


def node_run_spf_scan(state: AuditState) -> dict:
    """Node: Runs the SinglePointOfFailureAgent if SPF scanning is enabled.

    Args:
        state: Current AuditState.

    Returns:
        Partial state update with spf_findings count and node_history.
    """
    logger.info("Node: run_spf_scan")

    if not state.get("run_spf_scan"):
        logger.debug("SPF scan skipped by scope.")
        return {"node_history": ["run_spf_scan"]}

    try:
        output = _audit_orchestrator._spf_agent.scan()
        return {
            "spf_findings": output.spf_count,
            "node_history": ["run_spf_scan"],
        }
    except Exception as exc:
        logger.error("run_spf_scan node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["run_spf_scan"],
        }


def node_aggregate_audit(state: AuditState) -> dict:
    """Node: Aggregates all audit scan results into a unified AuditReport.

    Args:
        state: Current AuditState with all scan findings populated.

    Returns:
        Partial state update with audit_report and node_history.
    """
    logger.info(
        "Node: aggregate_audit | gap={} | staleness={} | spf={}",
        state.get("gap_findings", 0),
        state.get("staleness_findings", 0),
        state.get("spf_findings", 0),
    )

    try:
        audit_request = AuditRequest(
            scope=AuditScope(state.get("scope", "full")),
            session_id=state.get("session_id"),
            generate_summary=state.get("generate_summary", True),
        )
        report = _audit_orchestrator.audit(audit_request)
        return {
            "audit_report": report,
            "node_history": ["aggregate_audit"],
        }
    except Exception as exc:
        logger.error("aggregate_audit node failed: {}", exc)
        return {
            "error": str(exc),
            "node_history": ["aggregate_audit"],
        }


def node_audit_respond(state: AuditState) -> dict:
    """Node: Final audit node — confirms audit report is ready.

    Args:
        state: Current AuditState with audit_report populated.

    Returns:
        Partial state update confirming completion.
    """
    logger.info(
        "Node: audit_respond | health='{}'",
        state.get("audit_report").overall_health
        if state.get("audit_report")
        else "N/A",
    )
    return {"node_history": ["audit_respond"]}


# ════════════════════════════════════════════════════════════════════════════
# MASTER GRAPH NODES
# ════════════════════════════════════════════════════════════════════════════

def node_master_receive(state: MasterState) -> dict:
    """Node: Entry point — logs and validates the incoming master request.

    Args:
        state: Current MasterState with raw_input populated.

    Returns:
        Partial state update with node_history.
    """
    logger.info(
        "Node: master_receive | id='{}' | type='{}'",
        state.get("request_id"),
        state.get("request_type"),
    )
    return {"node_history": ["master_receive"]}


def node_master_route_query(state: MasterState) -> dict:
    """Node: Routes a QUERY request through the Master Orchestrator.

    Args:
        state: Current MasterState.

    Returns:
        Partial state update with final_response and node_history.
    """
    logger.info("Node: master_route_query")

    start = time.perf_counter()

    try:
        raw = state.get("raw_input", {})
        request = MasterRequest(
            request_id=state["request_id"],
            request_type=RequestType.QUERY,
            session_id=state.get("session_id"),
            query=raw.get("query", ""),
            top_k=raw.get("top_k", 5),
        )
        response = master_orchestrator.process(request)
        processing_ms = round((time.perf_counter() - start) * 1000, 2)

        return {
            "routed_to": "RetrievalOrchestrator",
            "final_response": response.model_dump(),
            "success": response.success,
            "processing_time_ms": processing_ms,
            "node_history": ["master_route_query"],
        }
    except Exception as exc:
        logger.error("master_route_query node failed: {}", exc)
        return {
            "success": False,
            "error": str(exc),
            "node_history": ["master_route_query"],
        }


def node_master_route_capture(state: MasterState) -> dict:
    """Node: Routes a CAPTURE request through the Master Orchestrator.

    Args:
        state: Current MasterState.

    Returns:
        Partial state update with final_response and node_history.
    """
    logger.info("Node: master_route_capture")

    start = time.perf_counter()

    try:
        raw = state.get("raw_input", {})
        capture_request = CaptureRequest(**raw.get("capture_request", {}))
        request = MasterRequest(
            request_id=state["request_id"],
            request_type=RequestType.CAPTURE,
            session_id=state.get("session_id"),
            capture_request=capture_request,
        )
        response = master_orchestrator.process(request)
        processing_ms = round((time.perf_counter() - start) * 1000, 2)

        return {
            "routed_to": "CaptureOrchestrator",
            "final_response": response.model_dump(),
            "success": response.success,
            "processing_time_ms": processing_ms,
            "node_history": ["master_route_capture"],
        }
    except Exception as exc:
        logger.error("master_route_capture node failed: {}", exc)
        return {
            "success": False,
            "error": str(exc),
            "node_history": ["master_route_capture"],
        }


def node_master_route_audit(state: MasterState) -> dict:
    """Node: Routes an AUDIT request through the Master Orchestrator.

    Args:
        state: Current MasterState.

    Returns:
        Partial state update with final_response and node_history.
    """
    logger.info("Node: master_route_audit")

    start = time.perf_counter()

    try:
        raw = state.get("raw_input", {})
        request = MasterRequest(
            request_id=state["request_id"],
            request_type=RequestType.AUDIT,
            session_id=state.get("session_id"),
            audit_scope=AuditScope(raw.get("scope", "full")),
        )
        response = master_orchestrator.process(request)
        processing_ms = round((time.perf_counter() - start) * 1000, 2)

        return {
            "routed_to": "AuditOrchestrator",
            "final_response": response.model_dump(),
            "success": response.success,
            "processing_time_ms": processing_ms,
            "node_history": ["master_route_audit"],
        }
    except Exception as exc:
        logger.error("master_route_audit node failed: {}", exc)
        return {
            "success": False,
            "error": str(exc),
            "node_history": ["master_route_audit"],
        }


def node_master_respond(state: MasterState) -> dict:
    """Node: Final master node — confirms response is ready.

    Args:
        state: Current MasterState.

    Returns:
        Partial state update confirming completion.
    """
    logger.info(
        "Node: master_respond | success={} | time={}ms",
        state.get("success"),
        state.get("processing_time_ms"),
    )
    return {"node_history": ["master_respond"]}