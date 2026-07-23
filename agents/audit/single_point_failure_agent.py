"""
Module: agents/audit/single_point_failure_agent.py

Purpose:
    Identifies individuals who represent single points of failure in
    the institutional knowledge base — people whose departure would
    result in irreplaceable knowledge loss.

Responsibilities:
    - Analyse ChromaDB metadata to find dominant knowledge contributors.
    - Identify senders whose emails represent a disproportionate share
      of total institutional memory.
    - Query Neo4j to find people with no successors or backups.
    - Detect topic areas owned exclusively by one person.
    - Produce structured SinglePointOfFailure objects for each finding.
    - Report findings to the Audit Orchestrator for action.

Workflow:
    Phase 1 — Fetch all metadata from ChromaDB collection.
    Phase 2 — Analyse sender contribution distribution.
    Phase 3 — Detect topic monopolies per sender.
    Phase 4 — Query Neo4j for isolated person nodes.
    Phase 5 — Construct SinglePointOfFailure objects.
    Phase 6 — Generate executive summary via Gemini.
    Phase 7 — Return SPFScanOutput with all findings.
"""

from collections import Counter, defaultdict
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


# ── Single Point of Failure Model ────────────────────────────────────────────

class SinglePointOfFailure(BaseModel):
    """Represents one identified single point of failure in institutional memory.

    Attributes:
        spf_id: Unique identifier for this finding.
        person_email: Email address of the at-risk person.
        person_name: Display name if available.
        department: Department this person belongs to.
        document_count: Number of documents this person contributed.
        contribution_percent: Their share of total institutional memory.
        owned_topics: Topics where this person is the sole contributor.
        risk_level: CRITICAL, HIGH, or MEDIUM risk level.
        description: Human-readable description of the risk.
        recommended_action: Suggested action to mitigate the risk.
    """

    spf_id: str = Field(..., description="Unique finding identifier")
    person_email: str = Field(..., description="Email of at-risk person")
    person_name: str = Field(
        default="Unknown", description="Display name of person"
    )
    department: str = Field(
        default="Unknown", description="Department of person"
    )
    document_count: int = Field(
        ..., description="Number of documents contributed"
    )
    contribution_percent: float = Field(
        ..., description="Percentage of total memory contributed"
    )
    owned_topics: list[str] = Field(
        default_factory=list,
        description="Topics where this person is the sole contributor"
    )
    risk_level: str = Field(..., description="CRITICAL, HIGH, or MEDIUM")
    description: str = Field(..., description="Description of the SPF risk")
    recommended_action: str = Field(
        ..., description="Action to mitigate this SPF risk"
    )


class SPFScanOutput(BaseModel):
    """Structured output produced by the Single Point of Failure Agent scan."""

    total_documents: int = Field(..., description="Total documents scanned")
    total_contributors: int = Field(
        ..., description="Total unique contributors found"
    )
    spf_count: int = Field(..., description="Total SPF findings detected")
    critical_spf_count: int = Field(
        ..., description="Number of CRITICAL risk SPF findings"
    )
    findings: list[SinglePointOfFailure] = Field(
        default_factory=list,
        description="All SPF findings ordered by risk level"
    )
    scanned_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str = Field(..., description="Executive summary of SPF findings")


# ── SPF Detection Thresholds ─────────────────────────────────────────────────

# Person contributes more than this % of total memory → CRITICAL
_CRITICAL_CONTRIBUTION_PERCENT = 25.0

# Person contributes more than this % of total memory → HIGH
_HIGH_CONTRIBUTION_PERCENT = 15.0

# Person contributes more than this % of total memory → MEDIUM
_MEDIUM_CONTRIBUTION_PERCENT = 10.0

# Minimum documents to be considered a significant contributor
_MIN_SIGNIFICANT_CONTRIBUTION = 20

# Topic ownership threshold — person owns this % of topic docs → monopoly
_TOPIC_MONOPOLY_PERCENT = 70.0

# Topic probe keywords mapped to topic label
_TOPIC_PROBES: dict[str, str] = {
    "Finance & Budgeting": "budget revenue financial cost expense profit",
    "Legal & Compliance": "legal contract compliance regulation audit",
    "Trading Operations": "trade market energy position deal price forward",
    "Technology & Systems": "system software database server infrastructure",
    "Strategy & Planning": "strategy plan vision goal objective initiative",
    "HR & People": "salary employee hire resign performance review training",
    "Risk Management": "risk control mitigation exposure assessment",
    "Project Management": "project timeline milestone deadline delivery scope",
}


class SinglePointOfFailureAgent(BaseAgent):
    """Audit agent that identifies single points of knowledge failure.

    Analyses contribution patterns in ChromaDB to identify individuals
    whose departure would cause disproportionate institutional knowledge
    loss, and topics that are exclusively owned by one person.

    Reports findings to the Audit Orchestrator with risk levels and
    concrete mitigation recommendations.
    """

    def __init__(self, memory=None) -> None:
        """Initialises the SinglePointOfFailureAgent.

        Args:
            memory: Optional MemoryManager for dependency injection.
        """
        super().__init__(
            agent_name="SinglePointOfFailureAgent",
            category=QueryCategory.UNKNOWN,
            memory=memory,
        )

        self._chroma_client = chromadb.PersistentClient(
            path=settings.chromadb.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _build_prompt(self, query: str, context: str) -> str:
        """Builds the SPF analysis summary prompt for Gemini.

        Args:
            query: Unused — kept for BaseAgent interface compliance.
            context: Structured SPF findings for LLM summarisation.

        Returns:
            The complete prompt string to send to Gemini.
        """
        return f"""
You are the Single Point of Failure Detection Agent for a Corporate
Institutional Memory System. Analyse the following risk findings and
produce a concise executive summary.

SPF FINDINGS:
{context}

INSTRUCTIONS:
1. Identify the highest-risk individuals and explain why they pose a risk.
2. Describe the business impact if each critical person left tomorrow.
3. Recommend the top 3 most urgent knowledge transfer actions.
4. Suggest structural changes to prevent future knowledge monopolies.
5. Keep the summary under 350 words.
6. Use clear, executive-friendly language.

Write the summary now:
""".strip()

    def _fetch_all_metadata(self) -> list[dict]:
        """Fetches all document metadata from ChromaDB.

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

    def _analyse_contribution_distribution(
        self,
        metadatas: list[dict],
    ) -> list[SinglePointOfFailure]:
        """Identifies senders with disproportionate knowledge contribution.

        Computes each sender's share of total institutional memory and
        flags those above the defined thresholds as SPF risks.

        Args:
            metadatas: All chunk metadata from ChromaDB.

        Returns:
            List of SinglePointOfFailure objects for at-risk contributors.
        """
        findings: list[SinglePointOfFailure] = []
        total_docs = len(metadatas)

        if total_docs == 0:
            return findings

        # Count contributions per sender
        sender_counts: Counter = Counter()
        sender_departments: dict[str, str] = {}

        for meta in metadatas:
            sender = meta.get("sender", "").strip().lower()
            department = meta.get("department", "Unknown")

            if not sender:
                continue

            sender_counts[sender] += 1

            # Keep most frequently seen department per sender
            if sender not in sender_departments:
                sender_departments[sender] = department

        for sender, count in sender_counts.items():
            if count < _MIN_SIGNIFICANT_CONTRIBUTION:
                continue

            contribution_percent = round((count / total_docs) * 100, 2)

            if contribution_percent < _MEDIUM_CONTRIBUTION_PERCENT:
                continue

            # Classify risk level
            if contribution_percent >= _CRITICAL_CONTRIBUTION_PERCENT:
                risk_level = "CRITICAL"
            elif contribution_percent >= _HIGH_CONTRIBUTION_PERCENT:
                risk_level = "HIGH"
            else:
                risk_level = "MEDIUM"

            spf_id = (
                f"spf_{sender.replace('@', '_').replace('.', '_')}"
            )

            findings.append(
                SinglePointOfFailure(
                    spf_id=spf_id,
                    person_email=sender,
                    department=sender_departments.get(sender, "Unknown"),
                    document_count=count,
                    contribution_percent=contribution_percent,
                    risk_level=risk_level,
                    description=(
                        f"'{sender}' contributes {contribution_percent}% "
                        f"({count} documents) of total institutional memory. "
                        f"Their departure would cause significant knowledge loss."
                    ),
                    recommended_action=(
                        f"Initiate a structured knowledge transfer programme "
                        f"with '{sender}'. Document their key decisions, "
                        f"processes, and relationships in the memory system."
                    ),
                )
            )

        return findings

    def _analyse_topic_monopolies(
        self,
        metadatas: list[dict],
        spf_findings: list[SinglePointOfFailure],
    ) -> None:
        """Detects topics exclusively owned by identified SPF individuals.

        For each SPF person found, analyses whether they are the sole
        or dominant contributor across critical business topics. Updates
        the owned_topics field of existing SPF findings in place.

        Args:
            metadatas: All chunk metadata from ChromaDB.
            spf_findings: Existing SPF findings to enrich with topic data.
        """
        if not spf_findings:
            return

        spf_emails = {f.person_email for f in spf_findings}

        # Build topic → sender → count mapping
        topic_sender_counts: dict[str, Counter] = defaultdict(Counter)

        for meta in metadatas:
            sender = meta.get("sender", "").strip().lower()
            subject = meta.get("subject", "").lower()
            department = meta.get("department", "").lower()
            combined = f"{subject} {department}"

            for topic_label, keywords in _TOPIC_PROBES.items():
                if any(kw in combined for kw in keywords.split()):
                    topic_sender_counts[topic_label][sender] += 1

        # Enrich SPF findings with owned topics
        for finding in spf_findings:
            email = finding.person_email
            owned: list[str] = []

            for topic_label, sender_counts in topic_sender_counts.items():
                total_topic_docs = sum(sender_counts.values())
                if total_topic_docs == 0:
                    continue

                person_topic_docs = sender_counts.get(email, 0)
                person_topic_percent = (
                    person_topic_docs / total_topic_docs
                ) * 100

                if person_topic_percent >= _TOPIC_MONOPOLY_PERCENT:
                    owned.append(topic_label)

            if owned:
                finding.owned_topics = owned
                # Escalate to CRITICAL if person owns multiple topics
                if len(owned) >= 2 and finding.risk_level != "CRITICAL":
                    finding.risk_level = "CRITICAL"
                    finding.description += (
                        f" Additionally, they are the sole contributor "
                        f"for: {', '.join(owned)}."
                    )

    def _analyse_graph_isolation(self) -> list[SinglePointOfFailure]:
        """Queries Neo4j for Person nodes with no incoming relationships.

        Isolated person nodes — those with no COMMUNICATED_WITH or
        INVOLVED_IN relationships — represent knowledge silos that
        exist only in one person's email history.

        Returns:
            List of SinglePointOfFailure objects for isolated graph nodes.
        """
        findings: list[SinglePointOfFailure] = []

        if not self._memory._graph_store:
            return findings

        try:
            with self._memory._graph_store._session() as session:
                # Find Person nodes with no relationships at all
                cypher = """
                    MATCH (p:Person)
                    WHERE NOT (p)-[]-()
                    RETURN p.email AS email,
                           p.name AS name,
                           p.department AS department
                    LIMIT 20
                """
                result = session.run(cypher)
                isolated = [dict(record) for record in result]

                for person in isolated:
                    email = person.get("email", "unknown")
                    name = person.get("name", "Unknown")
                    dept = person.get("department", "Unknown")

                    findings.append(
                        SinglePointOfFailure(
                            spf_id=f"spf_isolated_{email.replace('@', '_').replace('.', '_')}",
                            person_email=email,
                            person_name=name,
                            department=dept or "Unknown",
                            document_count=0,
                            contribution_percent=0.0,
                            risk_level="MEDIUM",
                            description=(
                                f"'{email}' exists as an isolated node in the "
                                f"knowledge graph with no recorded relationships. "
                                f"Their knowledge is siloed and undiscoverable."
                            ),
                            recommended_action=(
                                f"Map '{email}' relationships by ingesting their "
                                f"communications and linking them to decisions "
                                f"and projects in the knowledge graph."
                            ),
                        )
                    )

        except Exception as exc:
            logger.debug("Graph isolation analysis failed: {}", exc)

        return findings

    def _build_findings_context(
        self,
        findings: list[SinglePointOfFailure],
    ) -> str:
        """Formats SPF findings into a string for LLM summarisation.

        Args:
            findings: List of SinglePointOfFailure objects to format.

        Returns:
            Formatted string representation of all findings.
        """
        if not findings:
            return "No single points of failure detected."

        lines: list[str] = []
        for finding in findings:
            lines.append(
                f"SPF ID          : {finding.spf_id}\n"
                f"Risk Level      : {finding.risk_level}\n"
                f"Person          : {finding.person_email}\n"
                f"Department      : {finding.department}\n"
                f"Contribution    : {finding.contribution_percent}% "
                f"({finding.document_count} docs)\n"
                f"Owned Topics    : {', '.join(finding.owned_topics) or 'None'}\n"
                f"Description     : {finding.description}\n"
                f"Action          : {finding.recommended_action}\n"
            )

        return "\n---\n".join(lines)

    def scan(self) -> SPFScanOutput:
        """Performs a full single point of failure scan.

        This is the primary public method called by the Audit Orchestrator.
        Runs all analysis phases and aggregates findings into a structured
        SPFScanOutput.

        Returns:
            An SPFScanOutput containing all findings and executive summary.
        """
        logger.info(
            "SinglePointOfFailureAgent starting SPF scan."
        )

        # ── Phase 1: Fetch metadata ───────────────────────────────────────────
        metadatas = self._fetch_all_metadata()
        total_docs = len(metadatas)

        if total_docs == 0:
            return SPFScanOutput(
                total_documents=0,
                total_contributors=0,
                spf_count=1,
                critical_spf_count=1,
                findings=[
                    SinglePointOfFailure(
                        spf_id="spf_empty_collection",
                        person_email="N/A",
                        document_count=0,
                        contribution_percent=0.0,
                        risk_level="CRITICAL",
                        description="ChromaDB collection is empty.",
                        recommended_action=(
                            "Run the ingestion pipeline to populate "
                            "the institutional memory."
                        ),
                    )
                ],
                summary="CRITICAL: Institutional memory is empty.",
            )

        # ── Phase 2: Contribution distribution analysis ───────────────────────
        spf_findings = self._analyse_contribution_distribution(metadatas)

        # ── Phase 3: Topic monopoly analysis ─────────────────────────────────
        self._analyse_topic_monopolies(metadatas, spf_findings)

        # ── Phase 4: Graph isolation analysis ────────────────────────────────
        graph_findings = self._analyse_graph_isolation()

        # ── Aggregate all findings ────────────────────────────────────────────
        all_findings = spf_findings + graph_findings

        # Sort by risk level: CRITICAL first
        risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        all_findings.sort(
            key=lambda f: risk_order.get(f.risk_level, 3)
        )

        critical_count = sum(
            1 for f in all_findings if f.risk_level == "CRITICAL"
        )

        total_contributors = len({
            meta.get("sender", "")
            for meta in metadatas
            if meta.get("sender")
        })

        # ── Phase 5: Generate executive summary ───────────────────────────────
        findings_context = self._build_findings_context(all_findings[:10])
        prompt = self._build_prompt("spf analysis", findings_context)

        try:
            summary = self._invoke_llm(prompt)
        except Exception as exc:
            logger.warning("LLM summary generation failed: {}", exc)
            summary = (
                f"SPF scan complete. Found {len(all_findings)} findings "
                f"({critical_count} critical) across "
                f"{total_contributors} contributors."
            )

        logger.info(
            "SinglePointOfFailureAgent scan complete | "
            "contributors={} | findings={} | critical={}",
            total_contributors,
            len(all_findings),
            critical_count,
        )

        return SPFScanOutput(
            total_documents=total_docs,
            total_contributors=total_contributors,
            spf_count=len(all_findings),
            critical_spf_count=critical_count,
            findings=all_findings,
            summary=summary,
        )

    def run(self, agent_input: AgentInput) -> AgentOutput:
        """Implements BaseAgent.run() for orchestrator compatibility.

        Args:
            agent_input: Standard AgentInput — query field is unused.

        Returns:
            AgentOutput where answer contains the SPF summary and
            follow_up_questions lists the top recommended actions.
        """
        scan_result = self.scan()

        follow_ups = [
            finding.recommended_action
            for finding in scan_result.findings[:3]
        ]

        return self._build_output(
            query=agent_input.query or "single point of failure scan",
            answer=scan_result.summary,
            sources=[],
            status=AgentStatus.SUCCESS,
            confidence=1.0,
            follow_up_questions=follow_ups,
        )