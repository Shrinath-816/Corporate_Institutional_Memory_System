"""
Module: agents/audit/gap_detector_agent.py

Purpose:
    Detects gaps in the institutional knowledge base by analysing
    ChromaDB coverage across departments, topics, and time periods.

Responsibilities:
    - Scan the ChromaDB collection metadata to identify coverage gaps.
    - Detect departments with insufficient documentation.
    - Detect topic areas with sparse or missing coverage.
    - Detect time periods with no email evidence.
    - Produce structured KnowledgeGap objects for each gap found.
    - Report gaps to the Audit Orchestrator for action.

Workflow:
    Phase 1 — Fetch all metadata from ChromaDB collection.
    Phase 2 — Analyse department coverage distribution.
    Phase 3 — Analyse topic coverage using keyword probing.
    Phase 4 — Analyse temporal coverage for date gaps.
    Phase 5 — Construct KnowledgeGap objects for each finding.
    Phase 6 — Return a GapDetectorOutput with all gaps found.
"""

from collections import Counter
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger
from pydantic import BaseModel, Field

from agents.base_agent import BaseAgent
from config.settings import settings
from schemas.agent_schema import (
    AgentInput,
    AgentOutput,
    AgentStatus,
    QueryCategory,
)
from schemas.memory_schema import KnowledgeGap, KnowledgeGapSeverity


# ── Gap Detector Output Model ────────────────────────────────────────────────

class GapDetectorOutput(BaseModel):
    """Structured output produced by the Gap Detector Agent.

    Contains all knowledge gaps detected across departments,
    topics, and time periods in the institutional memory.
    """

    total_documents: int = Field(
        ..., description="Total documents in ChromaDB at time of scan"
    )
    gaps_found: int = Field(
        ..., description="Total number of knowledge gaps detected"
    )
    critical_gaps: int = Field(
        ..., description="Number of CRITICAL severity gaps found"
    )
    gaps: list[KnowledgeGap] = Field(
        default_factory=list,
        description="List of all detected KnowledgeGap objects"
    )
    scanned_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when this gap scan was performed"
    )
    summary: str = Field(
        ..., description="Human-readable summary of the gap analysis"
    )


# ── Topic Probes for Coverage Analysis ──────────────────────────────────────
# Each probe tests whether a critical business topic has sufficient coverage.

_TOPIC_PROBES: dict[str, str] = {
    "financial_decisions": "budget revenue financial cost expense",
    "legal_compliance": "legal contract compliance regulation lawsuit",
    "hr_policies": "salary employee hire resign performance review",
    "trading_operations": "trade market energy position deal price",
    "technology_systems": "system software database server network",
    "strategy_planning": "strategy plan vision goal objective initiative",
    "project_management": "project timeline milestone deadline delivery",
    "risk_management": "risk audit control mitigation exposure",
}

# Minimum document count per department to be considered adequate coverage
_MIN_DEPT_COVERAGE = 10

# Minimum document count per topic probe to be considered adequate coverage
_MIN_TOPIC_COVERAGE = 5


class GapDetectorAgent(BaseAgent):
    """Audit agent that scans institutional memory for knowledge gaps.

    Performs a systematic analysis of ChromaDB collection metadata
    to identify departments, topics, and time periods that lack
    sufficient documentation in the institutional memory.

    Unlike retrieval agents, this agent does not answer user queries —
    it proactively scans and reports gaps to the Audit Orchestrator.
    """

    def __init__(self, memory=None) -> None:
        """Initialises the GapDetectorAgent.

        Args:
            memory: Optional MemoryManager for dependency injection.
        """
        super().__init__(
            agent_name="GapDetectorAgent",
            category=QueryCategory.UNKNOWN,
            memory=memory,
        )

        # Direct ChromaDB client for metadata-level collection scanning
        self._chroma_client = chromadb.PersistentClient(
            path=settings.chromadb.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _build_prompt(self, query: str, context: str) -> str:
        """Builds a gap analysis summary prompt for Gemini.

        Args:
            query: Description of gaps found for LLM summarisation.
            context: Structured gap data to summarise.

        Returns:
            The complete prompt string to send to Gemini.
        """
        return f"""
You are the Knowledge Gap Detector for a Corporate Institutional Memory System.
Analyse the following gap data and produce a concise executive summary.

GAP DATA:
{context}

INSTRUCTIONS:
1. Summarise the most critical knowledge gaps found.
2. Explain the business risk each critical gap poses.
3. Suggest the top 3 actions to close the most important gaps.
4. Keep the summary under 300 words.
5. Use clear, executive-friendly language.

Write the summary now:
""".strip()

    def _fetch_all_metadata(self) -> list[dict]:
        """Fetches all document metadata from the ChromaDB collection.

        Retrieves metadata for every stored chunk to enable
        distribution analysis across departments and time periods.

        Returns:
            List of metadata dictionaries for all stored chunks.
        """
        try:
            collection = self._chroma_client.get_or_create_collection(
                name=settings.chromadb.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

            total = collection.count()
            if total == 0:
                logger.warning("ChromaDB collection is empty.")
                return []

            # Fetch all metadata — no embeddings needed for gap analysis
            result = collection.get(include=["metadatas"])
            return result["metadatas"] or []

        except Exception as exc:
            logger.error("Failed to fetch ChromaDB metadata: {}", exc)
            return []

    def _analyse_department_coverage(
        self,
        metadatas: list[dict],
    ) -> list[KnowledgeGap]:
        """Detects departments with insufficient documentation coverage.

        Args:
            metadatas: All chunk metadata from ChromaDB.

        Returns:
            List of KnowledgeGap objects for under-covered departments.
        """
        gaps: list[KnowledgeGap] = []

        # Count documents per department
        dept_counts: Counter = Counter()
        for meta in metadatas:
            dept = meta.get("department", "").strip()
            if dept:
                dept_counts[dept] += 1
            else:
                dept_counts["Unknown Department"] += 1

        logger.debug("Department coverage: {}", dict(dept_counts))

        for dept, count in dept_counts.items():
            if count < _MIN_DEPT_COVERAGE:
                severity = (
                    KnowledgeGapSeverity.CRITICAL
                    if count < 3
                    else KnowledgeGapSeverity.HIGH
                    if count < 6
                    else KnowledgeGapSeverity.MEDIUM
                )

                gaps.append(
                    KnowledgeGap(
                        gap_id=f"dept_gap_{dept.lower().replace(' ', '_')}",
                        description=(
                            f"Department '{dept}' has only {count} documents "
                            f"in institutional memory (minimum: {_MIN_DEPT_COVERAGE})."
                        ),
                        affected_area=dept,
                        severity=severity,
                        recommended_action=(
                            f"Ingest additional emails and documents from the "
                            f"'{dept}' department to reach adequate coverage."
                        ),
                    )
                )

        return gaps

    def _analyse_topic_coverage(self) -> list[KnowledgeGap]:
        """Probes ChromaDB for coverage across critical business topics.

        For each topic probe, performs a semantic search and checks
        whether sufficient documents are returned. Topics with fewer
        than the minimum threshold are flagged as gaps.

        Returns:
            List of KnowledgeGap objects for under-covered topics.
        """
        gaps: list[KnowledgeGap] = []

        for topic_key, probe_query in _TOPIC_PROBES.items():
            try:
                results = self._memory.search(
                    query=probe_query,
                    top_k=_MIN_TOPIC_COVERAGE,
                    use_cache=False,
                    agent_context=self.agent_name,
                )

                doc_count = len(results)

                if doc_count < _MIN_TOPIC_COVERAGE:
                    severity = (
                        KnowledgeGapSeverity.CRITICAL
                        if doc_count == 0
                        else KnowledgeGapSeverity.HIGH
                        if doc_count < 2
                        else KnowledgeGapSeverity.MEDIUM
                    )

                    topic_label = topic_key.replace("_", " ").title()

                    gaps.append(
                        KnowledgeGap(
                            gap_id=f"topic_gap_{topic_key}",
                            description=(
                                f"Topic '{topic_label}' has only {doc_count} "
                                f"relevant documents (minimum: {_MIN_TOPIC_COVERAGE})."
                            ),
                            affected_area=topic_label,
                            severity=severity,
                            recommended_action=(
                                f"Ingest emails, policies, or meeting notes "
                                f"related to '{topic_label}' to improve coverage."
                            ),
                        )
                    )

            except Exception as exc:
                logger.warning(
                    "Topic probe failed for '{}': {}", topic_key, exc
                )

        return gaps

    def _analyse_temporal_coverage(
        self,
        metadatas: list[dict],
    ) -> list[KnowledgeGap]:
        """Detects time periods with no email evidence in the memory.

        Parses dates from metadata and identifies months or years
        that have zero or very sparse documentation.

        Args:
            metadatas: All chunk metadata from ChromaDB.

        Returns:
            List of KnowledgeGap objects for temporal gaps.
        """
        gaps: list[KnowledgeGap] = []
        year_counts: Counter = Counter()

        for meta in metadatas:
            date_str = meta.get("date", "")
            if not date_str:
                continue

            try:
                # ISO format dates from ingestion pipeline
                year = datetime.fromisoformat(date_str).year
                year_counts[year] += 1
            except ValueError:
                continue

        if not year_counts:
            gaps.append(
                KnowledgeGap(
                    gap_id="temporal_gap_no_dates",
                    description=(
                        "No dated documents found in institutional memory. "
                        "Temporal analysis and timeline reconstruction are impossible."
                    ),
                    affected_area="All Departments",
                    severity=KnowledgeGapSeverity.CRITICAL,
                    recommended_action=(
                        "Ensure ingested emails contain valid date metadata."
                    ),
                )
            )
            return gaps

        # Detect years with very sparse coverage
        all_years = range(min(year_counts), max(year_counts) + 1)
        for year in all_years:
            count = year_counts.get(year, 0)
            if count < 5:
                gaps.append(
                    KnowledgeGap(
                        gap_id=f"temporal_gap_{year}",
                        description=(
                            f"Year {year} has only {count} documents in "
                            f"institutional memory — significant temporal gap."
                        ),
                        affected_area=f"Year {year}",
                        severity=(
                            KnowledgeGapSeverity.CRITICAL
                            if count == 0
                            else KnowledgeGapSeverity.MEDIUM
                        ),
                        recommended_action=(
                            f"Ingest historical emails and documents from "
                            f"year {year} to close this temporal gap."
                        ),
                    )
                )

        return gaps

    def _build_gap_context(self, gaps: list[KnowledgeGap]) -> str:
        """Formats detected gaps into a structured string for LLM summarisation.

        Args:
            gaps: List of KnowledgeGap objects to format.

        Returns:
            A formatted string representation of all gaps.
        """
        if not gaps:
            return "No significant knowledge gaps detected."

        lines: list[str] = []
        for gap in gaps:
            lines.append(
                f"Gap ID    : {gap.gap_id}\n"
                f"Severity  : {gap.severity.value}\n"
                f"Area      : {gap.affected_area}\n"
                f"Description: {gap.description}\n"
                f"Action    : {gap.recommended_action}\n"
            )

        return "\n---\n".join(lines)

    def scan(self) -> GapDetectorOutput:
        """Performs a full knowledge gap scan across all dimensions.

        This is the primary public method called by the Audit Orchestrator.
        Runs all three analysis phases and aggregates results into a
        structured GapDetectorOutput.

        Returns:
            A GapDetectorOutput containing all detected gaps and summary.
        """
        logger.info("GapDetectorAgent starting full knowledge gap scan.")

        # ── Phase 1: Fetch all metadata ───────────────────────────────────────
        metadatas = self._fetch_all_metadata()
        total_docs = len(metadatas)

        if total_docs == 0:
            return GapDetectorOutput(
                total_documents=0,
                gaps_found=1,
                critical_gaps=1,
                gaps=[
                    KnowledgeGap(
                        gap_id="gap_empty_collection",
                        description="ChromaDB collection is empty.",
                        affected_area="Entire System",
                        severity=KnowledgeGapSeverity.CRITICAL,
                        recommended_action=(
                            "Run the ingestion pipeline to populate "
                            "the institutional memory."
                        ),
                    )
                ],
                summary="CRITICAL: Institutional memory is empty. Run ingestion pipeline immediately.",
            )

        # ── Phase 2: Department coverage analysis ─────────────────────────────
        dept_gaps = self._analyse_department_coverage(metadatas)

        # ── Phase 3: Topic coverage analysis ─────────────────────────────────
        topic_gaps = self._analyse_topic_coverage()

        # ── Phase 4: Temporal coverage analysis ───────────────────────────────
        temporal_gaps = self._analyse_temporal_coverage(metadatas)

        # ── Phase 5: Aggregate all gaps ───────────────────────────────────────
        all_gaps = dept_gaps + topic_gaps + temporal_gaps

        # Sort by severity: CRITICAL first
        severity_order = {
            KnowledgeGapSeverity.CRITICAL: 0,
            KnowledgeGapSeverity.HIGH: 1,
            KnowledgeGapSeverity.MEDIUM: 2,
            KnowledgeGapSeverity.LOW: 3,
        }
        all_gaps.sort(key=lambda g: severity_order[g.severity])

        critical_count = sum(
            1 for g in all_gaps
            if g.severity == KnowledgeGapSeverity.CRITICAL
        )

        # ── Phase 6: Generate executive summary ───────────────────────────────
        gap_context = self._build_gap_context(all_gaps[:10])
        prompt = self._build_prompt("gap analysis summary", gap_context)

        try:
            summary = self._invoke_llm(prompt)
        except Exception as exc:
            logger.warning("LLM summary generation failed: {}", exc)
            summary = (
                f"Gap scan complete. Found {len(all_gaps)} gaps "
                f"({critical_count} critical) across {total_docs} documents."
            )

        logger.info(
            "GapDetectorAgent scan complete | total_docs={} | "
            "gaps={} | critical={}",
            total_docs,
            len(all_gaps),
            critical_count,
        )

        return GapDetectorOutput(
            total_documents=total_docs,
            gaps_found=len(all_gaps),
            critical_gaps=critical_count,
            gaps=all_gaps,
            summary=summary,
        )

    def run(self, agent_input: AgentInput) -> AgentOutput:
        """Implements BaseAgent.run() for orchestrator compatibility.

        Wraps scan() in the standard AgentOutput format so the
        gap detector can be used as a node in the LangGraph state machine.

        Args:
            agent_input: Standard AgentInput — query field is unused.

        Returns:
            AgentOutput where answer contains the gap analysis summary
            and follow_up_questions lists the top recommended actions.
        """
        scan_result = self.scan()

        follow_ups = [
            gap.recommended_action
            for gap in scan_result.gaps[:3]
        ]

        return self._build_output(
            query=agent_input.query or "knowledge gap scan",
            answer=scan_result.summary,
            sources=[],
            status=AgentStatus.SUCCESS,
            confidence=1.0,
            follow_up_questions=follow_ups,
        )