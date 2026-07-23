"""
Module: agents/retrieval/competitive_agent.py

Purpose:
    Retrieves and synthesises competitive intelligence answers by
    combining internal institutional memory with real-time web search.

Responsibilities:
    - Handle competitive intelligence queries routed by the orchestrator.
    - Search internal ChromaDB for historical competitive discussions.
    - Use LangChain web search tool to fetch current competitor data.
    - Synthesise a unified answer combining internal + external intelligence.
    - Link competitor activity to internal strategy decisions where possible.
    - Return structured sources and follow-up questions.

Workflow:
    Phase 1 — Receive AgentInput with a competitive intelligence query.
    Phase 2 — Search internal ChromaDB for competitor mentions.
    Phase 3 — Perform web search for current competitor information.
    Phase 4 — Query Neo4j for internal strategy decisions linked to competitor.
    Phase 5 — Build unified internal + external context.
    Phase 6 — Invoke Gemini to synthesise a competitive intelligence answer.
    Phase 7 — Parse follow-up questions from LLM response.
    Phase 8 — Return AgentOutput with answer, sources, and follow-ups.
"""

import re
from typing import Optional

from langchain_community.tools import DuckDuckGoSearchRun
from loguru import logger

from agents.base_agent import BaseAgent
from schemas.agent_schema import (
    AgentInput,
    AgentOutput,
    AgentStatus,
    QueryCategory,
)
from schemas.memory_schema import VectorSearchResult


class CompetitiveAgent(BaseAgent):
    """Specialist agent for competitive intelligence queries.

    Uniquely combines internal institutional memory (ChromaDB + Neo4j)
    with real-time web search to provide comprehensive competitive
    intelligence that links external market activity to internal
    strategic responses captured in email communications.
    """

    def __init__(self, memory=None) -> None:
        """Initialises the CompetitiveAgent with web search capability.

        Args:
            memory: Optional MemoryManager for dependency injection.
        """
        super().__init__(
            agent_name="CompetitiveAgent",
            category=QueryCategory.DECISION,
            memory=memory,
        )

        # Web search tool for external competitor intelligence
        self._web_search = DuckDuckGoSearchRun()

        logger.info("CompetitiveAgent initialised with web search.")

    def _build_prompt(self, query: str, context: str) -> str:
        """Builds the competitive intelligence RAG prompt for Gemini.

        Instructs the LLM to synthesise internal and external intelligence
        into a unified competitive analysis answer.

        Args:
            query: The user's original competitive intelligence query.
            context: Formatted string combining internal email evidence
                and external web search results.

        Returns:
            The complete prompt string to send to Gemini.
        """
        return f"""
You are the Competitive Intelligence Agent for a Corporate Institutional Memory System.
Your role is to answer questions about competitors, market positioning, and strategic
responses by combining internal company communications with current market intelligence.

RETRIEVED EVIDENCE (Internal Emails + External Web Intelligence):
{context}

USER QUERY:
{query}

INSTRUCTIONS:
1. Synthesise BOTH internal email evidence AND external web intelligence.
2. Clearly separate what was discussed INTERNALLY vs what is happening EXTERNALLY.
3. Identify how the company RESPONDED or planned to respond to competitor activity.
4. Highlight any STRATEGIC DECISIONS made in response to competitive pressure.
5. Note the TIME PERIOD of both internal discussions and external events.
6. Cite internal sources using [Source N] and external sources as [Web].
7. If internal evidence is sparse, rely on external intelligence but flag this.
8. Do not fabricate internal decisions not supported by the evidence.

After your main answer, provide exactly 3 follow-up questions:

FOLLOW_UP_1: <question>
FOLLOW_UP_2: <question>
FOLLOW_UP_3: <question>

Begin your answer now:
""".strip()

    def _extract_competitor_name(self, query: str) -> Optional[str]:
        """Extracts a competitor or company name from the query string.

        Uses capitalised word pattern matching to identify named
        organisations mentioned in the query.

        Args:
            query: The user's query string to analyse.

        Returns:
            The extracted competitor name string, or None if not found.
        """
        # Match sequences of capitalised words likely to be company names
        pattern = re.compile(
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:Inc|Corp|Ltd|LLC|Co))?)\b"
        )
        matches = pattern.findall(query)

        # Filter out common non-company words
        excluded = {
            "What", "Why", "Who", "How", "When", "Where",
            "Tell", "The", "Our", "Their", "Did", "Does",
        }

        candidates = [m for m in matches if m not in excluded]
        return candidates[0] if candidates else None

    def _extract_keywords(self, query: str) -> list[str]:
        """Extracts meaningful keywords from the competitive query.

        Args:
            query: The user's query string.

        Returns:
            A deduplicated list of keyword strings.
        """
        stop_words = {
            "what", "why", "who", "how", "when", "where", "is",
            "are", "the", "a", "an", "our", "we", "tell", "me",
            "about", "did", "does", "competitor", "competition",
            "competitive", "versus", "vs", "against",
        }

        keywords = [
            word.lower()
            for word in re.findall(r"\b[a-zA-Z]{3,}\b", query)
            if word.lower() not in stop_words
        ]

        return list(dict.fromkeys(keywords))

    def _search_internal_memory(
        self,
        query: str,
        competitor_name: Optional[str],
        top_k: int,
    ) -> list[VectorSearchResult]:
        """Searches ChromaDB for internal competitive intelligence.

        Performs two searches: one with the original query and one
        enriched with the competitor name for better recall.

        Args:
            query: The original user query string.
            competitor_name: Extracted competitor name for enrichment.
            top_k: Number of results to retrieve per search.

        Returns:
            Deduplicated list of VectorSearchResult objects.
        """
        results: list[VectorSearchResult] = []
        seen_ids: set[str] = set()

        # Primary semantic search
        primary_results = self._retrieve(query=query, top_k=top_k)
        for result in primary_results:
            if result.chunk_id not in seen_ids:
                seen_ids.add(result.chunk_id)
                results.append(result)

        # Enriched search with competitor name if available
        if competitor_name:
            enriched_query = f"{query} {competitor_name} strategy response"
            enriched_results = self._retrieve(
                query=enriched_query, top_k=top_k // 2
            )
            for result in enriched_results:
                if result.chunk_id not in seen_ids:
                    seen_ids.add(result.chunk_id)
                    results.append(result)

        return results

    def _search_web(self, query: str, competitor_name: Optional[str]) -> str:
        """Performs a web search for current competitor intelligence.

        Constructs a targeted search query and returns the raw
        web search results as a formatted string.

        Args:
            query: The original user query for context.
            competitor_name: Competitor name to focus the web search.

        Returns:
            Formatted web search results string, or empty string
            if web search fails or returns no results.
        """
        search_query = (
            f"{competitor_name} company strategy market 2024"
            if competitor_name
            else query
        )

        logger.info(
            "CompetitiveAgent web search | query='{}'", search_query
        )

        try:
            raw_results = self._web_search.run(search_query)

            if not raw_results or len(raw_results.strip()) < 50:
                logger.debug("Web search returned insufficient results.")
                return ""

            return f"\n[EXTERNAL WEB INTELLIGENCE]\n{raw_results[:2000]}\n"

        except Exception as exc:
            logger.warning("Web search failed: {}", exc)
            return ""

    def _build_graph_context(
        self,
        competitor_name: Optional[str],
        keywords: list[str],
    ) -> str:
        """Queries Neo4j for internal strategy decisions related to competitor.

        Searches Decision nodes for any strategic responses to competitor
        activity captured in the institutional memory graph.

        Args:
            competitor_name: Competitor name to search in decision summaries.
            keywords: Fallback keywords for broader graph search.

        Returns:
            Formatted string of graph-based strategy data, or empty
            string if graph unavailable or no matches found.
        """
        if not self._memory._graph_store:
            return ""

        graph_lines: list[str] = []
        search_terms = (
            [competitor_name.lower()] + keywords[:2]
            if competitor_name
            else keywords[:3]
        )

        try:
            for term in search_terms:
                decisions = self._memory.search_decisions_graph(term)
                if decisions:
                    if not graph_lines:
                        graph_lines.append(
                            "\n[GRAPH KNOWLEDGE - Internal Strategy Decisions]\n"
                        )
                    for decision in decisions[:3]:
                        graph_lines.append(
                            f"- Decision : {decision.get('summary', 'N/A')}\n"
                            f"  Date     : {decision.get('date', 'unknown')}\n"
                            f"  Dept     : {decision.get('department', 'unknown')}\n"
                        )

        except Exception as exc:
            logger.debug("CompetitiveAgent graph query failed: {}", exc)

        return "".join(graph_lines) if graph_lines else ""

    def _parse_follow_up_questions(
        self, llm_response: str
    ) -> tuple[str, list[str]]:
        """Separates the main answer from follow-up questions.

        Args:
            llm_response: The raw LLM response string.

        Returns:
            A tuple of (clean_answer, list_of_follow_up_questions).
        """
        pattern = re.compile(r"FOLLOW_UP_\d+:\s*(.+)", re.IGNORECASE)
        follow_ups = [m.strip() for m in pattern.findall(llm_response)]
        clean_answer = pattern.sub("", llm_response).strip()
        return clean_answer, follow_ups

    def _assess_confidence(
        self,
        internal_results: list[VectorSearchResult],
        web_context: str,
        answer: str,
    ) -> float:
        """Estimates answer confidence from internal and external sources.

        Applies separate weights to internal retrieval quality and
        web search availability to compute a blended confidence score.

        Args:
            internal_results: Retrieved internal VectorSearchResult objects.
            web_context: Web search result string (empty if unavailable).
            answer: The synthesised LLM answer string.

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        # Internal evidence component (weighted 60%)
        internal_score = 0.0
        if internal_results:
            avg_relevance = sum(
                r.relevance_score for r in internal_results
            ) / len(internal_results)
            internal_score = avg_relevance * 0.6

        # External web evidence component (weighted 40%)
        web_score = 0.4 if web_context else 0.0

        base_confidence = internal_score + web_score

        # Penalise if answer signals insufficient evidence
        insufficient_signals = [
            "no information", "cannot find", "not found",
            "no evidence", "sparse", "not available",
        ]
        penalty = 0.15 if any(
            s in answer.lower() for s in insufficient_signals
        ) else 0.0

        return max(0.0, round(min(1.0, base_confidence - penalty), 2))

    def run(self, agent_input: AgentInput) -> AgentOutput:
        """Executes the Competitive Agent's intelligence gathering pipeline.

        Args:
            agent_input: Standard AgentInput containing the query,
                top_k setting, and optional metadata filters.

        Returns:
            AgentOutput with a unified competitive intelligence answer
            combining internal memory and external web intelligence.
        """
        query = agent_input.query

        # ── Phase 2: Extract competitor identifier ────────────────────────────
        competitor_name = self._extract_competitor_name(query)
        keywords = self._extract_keywords(query)

        logger.info(
            "CompetitiveAgent | competitor='{}' | keywords={}",
            competitor_name or "unknown",
            keywords[:5],
        )

        # ── Phase 3: Search internal ChromaDB ────────────────────────────────
        internal_results = self._search_internal_memory(
            query=query,
            competitor_name=competitor_name,
            top_k=agent_input.top_k,
        )

        # ── Phase 4: Web search for external intelligence ─────────────────────
        web_context = self._search_web(query, competitor_name)

        # ── Phase 5: Query Neo4j for strategy decisions ───────────────────────
        graph_context = self._build_graph_context(competitor_name, keywords)

        # ── Phase 6: Build unified context ───────────────────────────────────
        if not internal_results and not web_context:
            return self._handle_empty_results(query)

        internal_context = (
            self._build_context(internal_results)
            if internal_results
            else "[No internal email evidence found for this competitor.]\n"
        )

        full_context_parts = [internal_context]
        if web_context:
            full_context_parts.append(web_context)
        if graph_context:
            full_context_parts.append(graph_context)

        full_context = "\n\n".join(full_context_parts)

        # ── Phase 7: Invoke LLM ───────────────────────────────────────────────
        prompt = self._build_prompt(query, full_context)

        try:
            raw_response = self._invoke_llm(prompt)
        except RuntimeError as exc:
            return self._build_output(
                query=query,
                answer=str(exc),
                sources=[],
                status=AgentStatus.FAILED,
                confidence=0.0,
            )

        # ── Phase 8: Parse and return output ─────────────────────────────────
        clean_answer, follow_ups = self._parse_follow_up_questions(raw_response)
        sources = self._extract_sources(internal_results)
        confidence = self._assess_confidence(
            internal_results, web_context, clean_answer
        )

        logger.info(
            "CompetitiveAgent answered | competitor='{}' | "
            "internal_sources={} | web={} | confidence={}",
            competitor_name or "unknown",
            len(sources),
            bool(web_context),
            confidence,
        )

        return self._build_output(
            query=query,
            answer=clean_answer,
            sources=sources,
            status=AgentStatus.SUCCESS,
            confidence=confidence,
            follow_up_questions=follow_ups,
        )