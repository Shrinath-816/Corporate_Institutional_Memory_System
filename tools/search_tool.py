"""
Module: tools/search_tool.py

Purpose:
    Provides a LangChain-compatible web search tool that lets agents
    retrieve current, real-world information not present in the
    institutional memory — competitor news, market context, or any
    external fact-checking an agent's reasoning requires.

Responsibilities:
    - Expose a general-purpose web_search @tool backed by DuckDuckGo.
    - Expose a web_search_news @tool for recency-biased news queries.
    - Truncate and format results into LLM-friendly strings.
    - Fail gracefully (never raise) so a search outage degrades an
      agent's answer rather than crashing its run.

Workflow:
    An agent (most notably CompetitiveAgent, which needs both internal
    memory and current market context) calls web_search or
    web_search_news mid-reasoning when it needs information the
    institutional memory cannot provide, then folds the result into
    its context before invoking the LLM for synthesis.

Design Notes (relationship to CompetitiveAgent's existing search call):
    agents/retrieval/competitive_agent.py already constructs its own
    `DuckDuckGoSearchRun()` instance directly in __init__, because at
    the time it was written no shared search tool existed yet. This
    module now provides that shared, reusable version — with result
    truncation, a dedicated news-biased variant, and consistent error
    handling — for any *other* agent that needs external search (e.g.
    a future agent verifying a captured decision against public
    reporting). CompetitiveAgent's inline instance is not being
    refactored to use this module in this pass, to avoid touching
    agent code as a side effect of adding a tool file; migrating it is
    a safe, mechanical follow-up (replace `self._web_search =
    DuckDuckGoSearchRun()` + `self._web_search.run(query)` with
    `from tools.search_tool import web_search` and a direct call).

    DuckDuckGo is used rather than a paid search API (Google/Bing/
    Tavily) because it requires no API key — consistent with this
    project having zero external paid-service dependencies beyond the
    Gemini LLM itself. If a higher-quality/rate-limit-safe provider is
    needed later, only _run_search() below needs to change; the public
    @tool signatures can stay the same.
"""

from typing import Optional

from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool
from loguru import logger


# ── Shared Search Backend ─────────────────────────────────────────────────────

_search_backend = DuckDuckGoSearchRun()

_MAX_RESULT_CHARS = 2000
_MIN_MEANINGFUL_RESULT_CHARS = 50


def _run_search(query: str, suffix: str = "") -> str:
    """Executes a search against the shared backend with consistent handling.

    Args:
        query: The base search query string.
        suffix: Optional string appended to bias results (e.g. "news 2026").

    Returns:
        The truncated raw search result string. Returns an empty string
        if the search fails or returns an insufficiently informative result.
    """
    full_query = f"{query} {suffix}".strip()

    try:
        raw_result = _search_backend.run(full_query)
    except Exception as exc:
        logger.warning("Web search failed for query '{}': {}", full_query, exc)
        return ""

    if not raw_result or len(raw_result.strip()) < _MIN_MEANINGFUL_RESULT_CHARS:
        logger.debug("Web search returned insufficient content for '{}'.", full_query)
        return ""

    return raw_result[:_MAX_RESULT_CHARS]


# ── LangChain Tool Wrappers ───────────────────────────────────────────────────

@tool
def web_search(query: str) -> str:
    """Searches the web for current, real-world information.

    Use this when you need information that is unlikely to be in the
    institutional email archive — current events, public company
    information, market data, or general facts to verify or supplement
    an internal answer.

    Args:
        query: The search query string.

    Returns:
        A string of relevant web search results, or a message
        indicating the search returned nothing useful.
    """
    if not query or not query.strip():
        return "Search query must not be empty."

    result = _run_search(query)

    if not result:
        return f"No useful web results found for '{query}'."

    logger.info("web_search tool executed | query='{}'", query[:60])
    return result


@tool
def web_search_news(query: str) -> str:
    """Searches the web for recent news related to the given topic.

    Use this specifically for time-sensitive information — recent
    company announcements, market moves, or industry developments —
    where recency matters more than general relevance.

    Args:
        query: The topic to search recent news for.

    Returns:
        A string of relevant recent news results, or a message
        indicating the search returned nothing useful.
    """
    if not query or not query.strip():
        return "Search query must not be empty."

    result = _run_search(query, suffix="latest news")

    if not result:
        return f"No recent news found for '{query}'."

    logger.info("web_search_news tool executed | query='{}'", query[:60])
    return result


# ── Tool Collection Export ────────────────────────────────────────────────────

SEARCH_TOOLS = [
    web_search,
    web_search_news,
]