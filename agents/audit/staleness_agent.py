"""
Module: agents/audit/staleness_agent.py

Purpose:
    Detects outdated or stale documents in the institutional memory
    by analysing the age and update frequency of stored content.

Responsibilities:
    - Scan ChromaDB metadata to identify documents not updated recently.
    - Detect policy documents that have not been reviewed in a threshold period.
    - Detect sender activity patterns to find inactive contributors.
    - Detect topic areas where content has not been refreshed recently.
    - Produce structured StalenessReport objects for each finding.
    - Report findings to the Audit Orchestrator for action.

Workflow:
    Phase 1 — Fetch all metadata from ChromaDB collection.
    Phase 2 — Analyse document age distribution.
    Phase 3 — Detect stale policy-related content.
    Phase 4 — Detect inactive sender/contributor patterns.
    Phase 5 — Construct StalenessReport objects for each finding.
    Phase 6 — Generate executive summary via Gemini.
    Phase 7 — Return StalenessScanOutput with all findings.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
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


# ── Staleness Report Model ───────────────────────────────────────────────────

class StalenessReport(BaseModel):
    """Represents a single staleness finding in the institutional memory.

    Attributes:
        report_id: Unique identifier for this staleness report.
        affected_area: Department, topic, or sender affected.
        last_activity: ISO date string of the most recent document.
        age_days: Number of days since last activity.
        severity: Staleness severity level.
        description: Human-readable description of the staleness issue.
        recommended_action: Suggested action to address the staleness.
    """

    report_id: str = Field(..., description="Unique staleness report identifier")
    affected_area: str = Field(..., description="Area affected by staleness")
    last_activity: str = Field(..., description="ISO date of most recent content")
    age_days: int = Field(..., description="Days since last activity")
    severity: str = Field(..., description="CRITICAL, HIGH, MEDIUM, or LOW")
    description: str = Field(..., description="Description of staleness issue")
    recommended_action: str = Field(..., description="Action to address staleness")


class StalenessScanOutput(BaseModel):
    """Structured output produced by the Staleness Agent scan.

    Contains all staleness findings across documents, policies,
    and contributor activity patterns.
    """

    total_documents: int = Field(
        ..., description="Total documents scanned"
    )
    total_findings: int = Field(
        ..., description="Total staleness findings detected"
    )
    critical_findings: int = Field(
        ..., description="Number of CRITICAL severity findings"
    )
    findings: list[StalenessReport] = Field(
        default_factory=list,
        description="All staleness findings"
    )
    oldest_document_date: Optional[str] = Field(
        None, description="ISO date of oldest document in memory"
    )
    newest_document_date: Optional[str] = Field(
        None, description="ISO date of newest document in memory"
    )
    scanned_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when this scan was performed"
    )
    summary: str = Field(
        ..., description="Executive summary of staleness findings"
    )


# ── Staleness Thresholds (in days) ──────────────────────────────────────────

_CRITICAL_AGE_DAYS = 1825   # 5 years
_HIGH_AGE_DAYS = 1095       # 3 years
_MEDIUM_AGE_DAYS = 365      # 1 year

# Keywords indicating policy-related content
_POLICY_KEYWORDS = [
    "policy", "procedure", "guideline", "compliance",
    "rule", "regulation", "standard", "protocol",
]


class StalenessAgent(BaseAgent):
    """Audit agent that detects stale content in institutional memory.

    Analyses document age, policy review cycles, and contributor
    activity patterns to surface content that may be outdated,
    inaccurate, or no longer reflective of current practices.

    Unlike retrieval agents, this agent proactively scans the memory
    and reports findings to the Audit Orchestrator.
    """

    def __init__(self, memory=None) -> None:
        """Initialises the StalenessAgent.

        Args:
            memory: Optional MemoryManager for dependency injection.
        """
        super().__init__(
            agent_name="StalenessAgent",
            category=QueryCategory.UNKNOWN,
            memory=memory,
        )

        self._chroma_client = chromadb.PersistentClient(
            path=settings.chromadb.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _build_prompt(self, query: str, context: str) -> str:
        """Builds a staleness summary prompt for Gemini.

        Args:
            query: Unused — kept for BaseAgent interface compliance.
            context: Structured staleness findings for summarisation.

        Returns:
            The complete prompt string to send to Gemini.
        """
        return f"""
You are the Staleness Detection Agent for a Corporate Institutional Memory System.
Analyse the following staleness findings and produce a concise executive summary.

STALENESS FINDINGS:
{context}

INSTRUCTIONS:
1. Summarise the most critical staleness issues found.
2. Explain the business risk of relying on outdated institutional memory.
3. Recommend the top 3 actions to refresh the most stale content.
4. Keep the summary under 300 words.
5. Use clear, executive-friendly language.

Write the summary now:
""".strip()

    def _fetch_all_metadata(self) -> list[dict]:
        """Fetches all document metadata from ChromaDB for staleness analysis.

        Returns:
            List of metadata dictionaries for all stored chunks.
        """
        try:
            collection = self._chroma_client.get_or_create_collection(
                name=settings.chromadb.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

            if collection.count() == 0:
                logger.warning("ChromaDB collection is empty.")
                return []

            result = collection.get(include=["metadatas"])
            return result["metadatas"] or []

        except Exception as exc:
            logger.error("Failed to fetch ChromaDB metadata: {}", exc)
            return []

    def _parse_dates(
        self, metadatas: list[dict]
    ) -> list[tuple[datetime, dict]]:
        """Parses date strings from metadata into datetime objects.

        Args:
            metadatas: All chunk metadata from ChromaDB.

        Returns:
            List of (datetime, metadata) tuples for chunks with valid dates.
        """
        dated: list[tuple[datetime, dict]] = []

        for meta in metadatas:
            date_str = meta.get("date", "")
            if not date_str:
                continue
            try:
                dt = datetime.fromisoformat(date_str)
                # Normalise to UTC-aware datetime for consistent comparison
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dated.append((dt, meta))
            except ValueError:
                continue

        return dated

    def _compute_age_days(self, dt: datetime) -> int:
        """Computes the age of a document in days from today.

        Args:
            dt: The document's datetime object.

        Returns:
            Integer number of days since the document date.
        """
        now = datetime.now(timezone.utc)
        return (now - dt).days

    def _classify_severity(self, age_days: int) -> str:
        """Classifies staleness severity based on document age.

        Args:
            age_days: Age of the document in days.

        Returns:
            Severity string: CRITICAL, HIGH, MEDIUM, or LOW.
        """
        if age_days >= _CRITICAL_AGE_DAYS:
            return "CRITICAL"
        if age_days >= _HIGH_AGE_DAYS:
            return "HIGH"
        if age_days >= _MEDIUM_AGE_DAYS:
            return "MEDIUM"
        return "LOW"

    def _analyse_overall_age(
        self,
        dated: list[tuple[datetime, dict]],
    ) -> list[StalenessReport]:
        """Detects departments where all content is older than threshold.

        Groups documents by department and checks whether the most
        recent document per department is above the staleness threshold.

        Args:
            dated: List of (datetime, metadata) tuples.

        Returns:
            List of StalenessReport objects for stale departments.
        """
        findings: list[StalenessReport] = []

        # Group most recent date per department
        dept_latest: dict[str, datetime] = {}
        for dt, meta in dated:
            dept = meta.get("department", "Unknown Department")
            if dept not in dept_latest or dt > dept_latest[dept]:
                dept_latest[dept] = dt

        for dept, latest_dt in dept_latest.items():
            age_days = self._compute_age_days(latest_dt)
            severity = self._classify_severity(age_days)

            # Only report as finding if content is at least 1 year old
            if age_days >= _MEDIUM_AGE_DAYS:
                findings.append(
                    StalenessReport(
                        report_id=f"stale_dept_{dept.lower().replace(' ', '_')}",
                        affected_area=dept,
                        last_activity=latest_dt.isoformat(),
                        age_days=age_days,
                        severity=severity,
                        description=(
                            f"Department '{dept}' has had no new documentation "
                            f"for {age_days} days. Most recent content dates "
                            f"to {latest_dt.strftime('%B %Y')}."
                        ),
                        recommended_action=(
                            f"Request updated emails, decisions, or policy "
                            f"documents from the '{dept}' department."
                        ),
                    )
                )

        return findings

    def _analyse_policy_staleness(
        self,
        dated: list[tuple[datetime, dict]],
    ) -> list[StalenessReport]:
        """Detects policy-related content that has not been refreshed.

        Filters chunks whose subject contains policy keywords and
        checks whether the most recent policy content is stale.

        Args:
            dated: List of (datetime, metadata) tuples.

        Returns:
            List of StalenessReport objects for stale policy content.
        """
        findings: list[StalenessReport] = []

        # Filter to policy-related chunks only
        policy_chunks: list[tuple[datetime, dict]] = [
            (dt, meta)
            for dt, meta in dated
            if any(
                keyword in meta.get("subject", "").lower() or
                keyword in meta.get("department", "").lower()
                for keyword in _POLICY_KEYWORDS
            )
        ]

        if not policy_chunks:
            findings.append(
                StalenessReport(
                    report_id="stale_policy_no_content",
                    affected_area="Policy Documentation",
                    last_activity="N/A",
                    age_days=0,
                    severity="HIGH",
                    description=(
                        "No policy-related content detected in institutional "
                        "memory. Policy documentation is absent."
                    ),
                    recommended_action=(
                        "Ingest policy documents, procedure manuals, and "
                        "compliance guidelines into the memory system."
                    ),
                )
            )
            return findings

        # Find most recent policy document
        latest_policy_dt = max(dt for dt, _ in policy_chunks)
        age_days = self._compute_age_days(latest_policy_dt)
        severity = self._classify_severity(age_days)

        if age_days >= _MEDIUM_AGE_DAYS:
            findings.append(
                StalenessReport(
                    report_id="stale_policy_content",
                    affected_area="Policy Documentation",
                    last_activity=latest_policy_dt.isoformat(),
                    age_days=age_days,
                    severity=severity,
                    description=(
                        f"Policy-related content in institutional memory has "
                        f"not been refreshed in {age_days} days. "
                        f"Policies may no longer reflect current practices."
                    ),
                    recommended_action=(
                        "Review and re-ingest current policy documents to "
                        "ensure the memory reflects up-to-date procedures."
                    ),
                )
            )

        return findings

    def _analyse_contributor_activity(
        self,
        dated: list[tuple[datetime, dict]],
    ) -> list[StalenessReport]:
        """Detects contributors whose last activity is significantly outdated.

        Identifies senders whose most recent email is above the staleness
        threshold, indicating potential knowledge that has not been captured.

        Args:
            dated: List of (datetime, metadata) tuples.

        Returns:
            List of StalenessReport for inactive high-activity contributors.
        """
        findings: list[StalenessReport] = []

        # Track latest activity and total count per sender
        sender_latest: dict[str, datetime] = {}
        sender_counts: Counter = Counter()

        for dt, meta in dated:
            sender = meta.get("sender", "").strip()
            if not sender:
                continue
            sender_counts[sender] += 1
            if sender not in sender_latest or dt > sender_latest[sender]:
                sender_latest[sender] = dt

        # Only flag high-activity senders who have gone silent
        high_activity_threshold = 10
        high_activity_senders = {
            sender
            for sender, count in sender_counts.items()
            if count >= high_activity_threshold
        }

        for sender in high_activity_senders:
            latest_dt = sender_latest[sender]
            age_days = self._compute_age_days(latest_dt)

            if age_days >= _HIGH_AGE_DAYS:
                severity = self._classify_severity(age_days)
                findings.append(
                    StalenessReport(
                        report_id=f"stale_contributor_{sender.replace('@', '_').replace('.', '_')}",
                        affected_area=f"Contributor: {sender}",
                        last_activity=latest_dt.isoformat(),
                        age_days=age_days,
                        severity=severity,
                        description=(
                            f"High-activity contributor '{sender}' "
                            f"({sender_counts[sender]} documents) has had "
                            f"no activity for {age_days} days. Their "
                            f"institutional knowledge may be at risk."
                        ),
                        recommended_action=(
                            f"Conduct a knowledge extraction session with "
                            f"'{sender}' or their successor to capture "
                            f"undocumented institutional knowledge."
                        ),
                    )
                )

        return findings

    def _build_findings_context(
        self, findings: list[StalenessReport]
    ) -> str:
        """Formats staleness findings into a string for LLM summarisation.

        Args:
            findings: List of StalenessReport objects to format.

        Returns:
            Formatted string representation of all findings.
        """
        if not findings:
            return "No significant staleness issues detected."

        lines: list[str] = []
        for finding in findings:
            lines.append(
                f"Report ID  : {finding.report_id}\n"
                f"Severity   : {finding.severity}\n"
                f"Area       : {finding.affected_area}\n"
                f"Age (days) : {finding.age_days}\n"
                f"Description: {finding.description}\n"
                f"Action     : {finding.recommended_action}\n"
            )

        return "\n---\n".join(lines)

    def scan(self) -> StalenessScanOutput:
        """Performs a full staleness scan across all memory dimensions.

        This is the primary public method called by the Audit Orchestrator.
        Runs all analysis phases and aggregates findings into a
        structured StalenessScanOutput.

        Returns:
            A StalenessScanOutput containing all findings and summary.
        """
        logger.info("StalenessAgent starting staleness scan.")

        # ── Phase 1: Fetch metadata ───────────────────────────────────────────
        metadatas = self._fetch_all_metadata()
        total_docs = len(metadatas)

        if total_docs == 0:
            return StalenessScanOutput(
                total_documents=0,
                total_findings=1,
                critical_findings=1,
                findings=[
                    StalenessReport(
                        report_id="stale_empty_collection",
                        affected_area="Entire System",
                        last_activity="N/A",
                        age_days=0,
                        severity="CRITICAL",
                        description="ChromaDB collection is empty.",
                        recommended_action=(
                            "Run the ingestion pipeline to populate "
                            "the institutional memory."
                        ),
                    )
                ],
                summary="CRITICAL: Institutional memory is empty.",
            )

        # ── Phase 2: Parse all dates ──────────────────────────────────────────
        dated = self._parse_dates(metadatas)

        if not dated:
            return StalenessScanOutput(
                total_documents=total_docs,
                total_findings=1,
                critical_findings=1,
                findings=[
                    StalenessReport(
                        report_id="stale_no_dates",
                        affected_area="Entire System",
                        last_activity="N/A",
                        age_days=0,
                        severity="HIGH",
                        description=(
                            "No documents with valid dates found. "
                            "Staleness analysis cannot be performed."
                        ),
                        recommended_action=(
                            "Ensure ingested documents contain valid "
                            "date metadata."
                        ),
                    )
                ],
                summary="HIGH: No dated documents found in institutional memory.",
            )

        # Compute date range statistics
        all_dates = [dt for dt, _ in dated]
        oldest_dt = min(all_dates)
        newest_dt = max(all_dates)

        # ── Phase 3: Analyse overall department age ───────────────────────────
        dept_findings = self._analyse_overall_age(dated)

        # ── Phase 4: Analyse policy staleness ────────────────────────────────
        policy_findings = self._analyse_policy_staleness(dated)

        # ── Phase 5: Analyse contributor activity ─────────────────────────────
        contributor_findings = self._analyse_contributor_activity(dated)

        # ── Aggregate all findings ────────────────────────────────────────────
        all_findings = dept_findings + policy_findings + contributor_findings

        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        all_findings.sort(
            key=lambda f: severity_order.get(f.severity, 4)
        )

        critical_count = sum(
            1 for f in all_findings if f.severity == "CRITICAL"
        )

        # ── Phase 6: Generate executive summary ───────────────────────────────
        findings_context = self._build_findings_context(all_findings[:10])
        prompt = self._build_prompt("staleness analysis", findings_context)

        try:
            summary = self._invoke_llm(prompt)
        except Exception as exc:
            logger.warning("LLM summary generation failed: {}", exc)
            summary = (
                f"Staleness scan complete. Found {len(all_findings)} findings "
                f"({critical_count} critical) across {total_docs} documents."
            )

        logger.info(
            "StalenessAgent scan complete | total_docs={} | "
            "findings={} | critical={}",
            total_docs,
            len(all_findings),
            critical_count,
        )

        return StalenessScanOutput(
            total_documents=total_docs,
            total_findings=len(all_findings),
            critical_findings=critical_count,
            findings=all_findings,
            oldest_document_date=oldest_dt.isoformat(),
            newest_document_date=newest_dt.isoformat(),
            summary=summary,
        )

    def run(self, agent_input: AgentInput) -> AgentOutput:
        """Implements BaseAgent.run() for orchestrator compatibility.

        Args:
            agent_input: Standard AgentInput — query field is unused.

        Returns:
            AgentOutput where answer contains the staleness summary
            and follow_up_questions lists the top recommended actions.
        """
        scan_result = self.scan()

        follow_ups = [
            finding.recommended_action
            for finding in scan_result.findings[:3]
        ]

        return self._build_output(
            query=agent_input.query or "staleness scan",
            answer=scan_result.summary,
            sources=[],
            status=AgentStatus.SUCCESS,
            confidence=1.0,
            follow_up_questions=follow_ups,
        )