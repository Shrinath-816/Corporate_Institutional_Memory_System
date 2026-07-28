"""
Module: tools/neo4j_tool.py

Purpose:
    Provides LangChain-compatible tools that let agents query the
    institutional knowledge graph directly — person profiles, decision
    history, communication networks, and (guarded) raw Cypher queries.

Responsibilities:
    - Expose read-oriented graph queries as @tool functions: person
      lookup, decisions by person/department, communication network,
      and department roster.
    - Provide a guarded run_cypher_query tool for ad-hoc read-only
      exploration, with write-keyword blocking to prevent an agent
      from mutating the graph through free-form Cypher.
    - Return LLM-friendly formatted strings, not raw dicts, since these
      tools are designed to be called mid-reasoning by an agent that
      needs to read the result back into its next thought.

Workflow:
    An agent (e.g. within a LangGraph ReAct-style loop) calls one of
    these tools when it needs graph context it doesn't already have
    from its own retrieval step — e.g. "who does this person usually
    work with?" — and incorporates the formatted result into its answer.

Design Notes (why this wraps MemoryManager instead of a new connection):
    memory/graph_store.py already owns the Neo4j driver lifecycle
    (connection pooling, constraints, session management) via the
    module-level `memory_manager` singleton in memory/memory_manager.py.
    Opening a second, independent Neo4j driver here would duplicate
    connection pools for no benefit and risk drifting out of sync with
    GraphStore's query patterns. Every tool in this file is therefore a
    thin, agent-facing wrapper around memory_manager's existing graph
    methods (or, where MemoryManager doesn't expose a method yet, a
    direct read-only session call via memory_manager._graph_store,
    following the same pattern already used in agents/policy_agent.py
    and agents/project_agent.py for ad-hoc Cypher).

    The run_cypher_query tool is the one exception that touches Neo4j
    more freely — it exists so an agent can explore graph shape during
    development/debugging without a new Python method per query shape.
    It is deliberately restricted to read-only statements: any query
    containing CREATE, MERGE, DELETE, SET, REMOVE, or DROP (case-
    insensitive) is rejected before it reaches the database. This is a
    strict, blunt keyword filter — not a full Cypher parser — and
    should not be treated as a security boundary against an adversarial
    query; it exists to prevent accidental mutation from a well-
    intentioned but imprecise agent-generated query, nothing more.
"""

import re
from typing import Optional

from langchain_core.tools import tool
from loguru import logger

from memory.memory_manager import memory_manager


# ── Write-Keyword Guard for Raw Cypher ────────────────────────────────────────

_WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|CALL\s+apoc\.)\b",
    re.IGNORECASE,
)


def _is_read_only_query(cypher: str) -> bool:
    """Checks whether a Cypher query string contains no write keywords.

    Args:
        cypher: The raw Cypher query string to check.

    Returns:
        True if no write-related keywords are found, False otherwise.
    """
    return not _WRITE_KEYWORDS.search(cypher)


# ── Formatting Helpers ────────────────────────────────────────────────────────

def _format_person(person: dict) -> str:
    """Formats a person dictionary into an LLM-readable line.

    Args:
        person: A raw person property dictionary from Neo4j.

    Returns:
        A single formatted line describing the person.
    """
    name = person.get("name", "Unknown")
    email = person.get("email", "unknown")
    role = person.get("role", "") or "role unknown"
    dept = person.get("department", "") or "department unknown"
    return f"{name} <{email}> — {role}, {dept}"


def _format_decision(decision: dict) -> str:
    """Formats a decision dictionary into an LLM-readable line.

    Args:
        decision: A raw decision property dictionary from Neo4j.

    Returns:
        A single formatted line describing the decision.
    """
    summary = decision.get("summary", "No summary")
    date = decision.get("date", "unknown date")
    dept = decision.get("department", "") or "unknown department"
    return f"[{date}] {summary} ({dept})"


# ── LangChain Tool Wrappers ───────────────────────────────────────────────────

@tool
def get_person_profile(email: str) -> str:
    """Looks up a person's profile in the institutional knowledge graph.

    Use this when you need a person's role, department, or basic
    identity information and don't already have it from retrieved
    email context.

    Args:
        email: The email address of the person to look up.

    Returns:
        A formatted string with the person's profile, or a message
        indicating no record was found.
    """
    if not memory_manager._graph_store:
        return "Graph store is unavailable — cannot look up person profiles."

    person = memory_manager.get_person(email)
    if not person:
        return f"No graph record found for '{email}'."

    return _format_person(person)


@tool
def get_person_decisions(email: str) -> str:
    """Retrieves all decisions a specific person has been involved in.

    Use this to understand a person's decision-making history or to
    verify who was behind a particular type of decision.

    Args:
        email: The email address of the person to look up.

    Returns:
        A formatted string listing their decisions, or a message
        indicating none were found.
    """
    if not memory_manager._graph_store:
        return "Graph store is unavailable — cannot look up decisions."

    decisions = memory_manager.get_decisions_by_person(email)
    if not decisions:
        return f"No recorded decisions found for '{email}'."

    lines = [_format_decision(d) for d in decisions[:10]]
    return f"{len(decisions)} decision(s) for {email}:\n" + "\n".join(lines)


@tool
def get_department_decisions(department: str) -> str:
    """Retrieves all decisions recorded for a specific department.

    Args:
        department: The department name to filter decisions by.

    Returns:
        A formatted string listing the department's decisions, or a
        message indicating none were found.
    """
    if not memory_manager._graph_store:
        return "Graph store is unavailable — cannot look up decisions."

    decisions = memory_manager.get_decisions_by_department(department)
    if not decisions:
        return f"No recorded decisions found for department '{department}'."

    lines = [_format_decision(d) for d in decisions[:10]]
    return f"{len(decisions)} decision(s) in {department}:\n" + "\n".join(lines)


@tool
def get_communication_network(email: str) -> str:
    """Retrieves the people a specific person has communicated with.

    Use this to understand someone's working relationships or to find
    who might have additional context on a topic that person handled.

    Args:
        email: The email address of the person to look up.

    Returns:
        A formatted string listing their known contacts, or a message
        indicating none were found.
    """
    if not memory_manager._graph_store:
        return "Graph store is unavailable — cannot look up communication network."

    network = memory_manager.get_communication_network(email)
    if not network:
        return f"No communication network recorded for '{email}'."

    lines = [_format_person(p) for p in network[:15]]
    return f"{len(network)} known contact(s) for {email}:\n" + "\n".join(lines)


@tool
def search_decisions_by_keyword(keyword: str) -> str:
    """Searches all decision summaries in the graph for a keyword match.

    Use this for broad topic-based decision searches when you don't
    have a specific person or department in mind.

    Args:
        keyword: The keyword to search for within decision summaries.

    Returns:
        A formatted string listing matching decisions, or a message
        indicating none were found.
    """
    if not memory_manager._graph_store:
        return "Graph store is unavailable — cannot search decisions."

    decisions = memory_manager.search_decisions_graph(keyword)
    if not decisions:
        return f"No decisions found matching '{keyword}'."

    lines = [_format_decision(d) for d in decisions[:10]]
    return f"{len(decisions)} decision(s) matching '{keyword}':\n" + "\n".join(lines)


@tool
def run_cypher_query(cypher: str) -> str:
    """Runs a read-only Cypher query against the knowledge graph.

    Use this only when the other, more specific graph tools don't cover
    what you need — e.g. exploring an unusual relationship shape. The
    query MUST be read-only: MATCH/RETURN/WHERE/WITH/ORDER BY/LIMIT are
    fine; CREATE, MERGE, DELETE, SET, REMOVE, and DROP are rejected.

    Args:
        cypher: The read-only Cypher query string to execute.

    Returns:
        A formatted string of the query results (up to 20 rows), or an
        error message if the query is rejected or fails.
    """
    if not memory_manager._graph_store:
        return "Graph store is unavailable — cannot run Cypher queries."

    if not _is_read_only_query(cypher):
        logger.warning(
            "run_cypher_query blocked a write-keyword query: {}", cypher
        )
        return (
            "Query rejected: only read-only Cypher is permitted "
            "(no CREATE, MERGE, DELETE, SET, REMOVE, or DROP)."
        )

    try:
        with memory_manager._graph_store._session() as session:
            result = session.run(cypher)
            records = [dict(record) for record in result][:20]

        if not records:
            return "Query executed successfully but returned no results."

        lines = [str(r) for r in records]
        return f"{len(records)} row(s) returned:\n" + "\n".join(lines)

    except Exception as exc:
        logger.error("run_cypher_query failed: {}", exc)
        return f"Query failed: {exc}"


# ── Tool Collection Export ────────────────────────────────────────────────────

NEO4J_TOOLS = [
    get_person_profile,
    get_person_decisions,
    get_department_decisions,
    get_communication_network,
    search_decisions_by_keyword,
    run_cypher_query,
]