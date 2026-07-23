"""
Module: agents/capture/meeting_agent.py

Purpose:
    Extracts and stores structured knowledge from meeting transcripts
    and meeting-related email communications into the institutional memory.

Responsibilities:
    - Accept raw meeting transcript text or meeting-related email content.
    - Extract decisions made, action items, owners, deadlines, and topics.
    - Store extracted knowledge as structured Decision nodes in Neo4j.
    - Store raw transcript chunks in ChromaDB for semantic retrieval.
    - Return a structured MeetingExtractionOutput with all findings.

Workflow:
    Phase 1 — Receive meeting transcript or email content.
    Phase 2 — Use Gemini to extract structured meeting intelligence.
    Phase 3 — Parse LLM response into structured meeting data.
    Phase 4 — Store Decision nodes and relationships in Neo4j.
    Phase 5 — Store transcript chunks in ChromaDB.
    Phase 6 — Return MeetingExtractionOutput with all extracted data.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from agents.base_agent import BaseAgent
from schemas.agent_schema import (
    AgentInput,
    AgentOutput,
    AgentStatus,
    QueryCategory,
)
from schemas.memory_schema import (
    DecisionNode,
    PersonNode,
    GraphRelationship,
    RelationshipType,
    NodeType,
)


# ── Meeting Data Models ──────────────────────────────────────────────────────

class ActionItem(BaseModel):
    """Represents a single action item extracted from a meeting."""

    description: str = Field(..., description="What needs to be done")
    owner: Optional[str] = Field(None, description="Person responsible")
    deadline: Optional[str] = Field(None, description="Due date if mentioned")


class MeetingDecision(BaseModel):
    """Represents a single decision extracted from a meeting."""

    summary: str = Field(..., description="Summary of the decision made")
    context: str = Field(default="", description="Context around the decision")
    participants: list[str] = Field(
        default_factory=list,
        description="People involved in making this decision"
    )


class MeetingExtractionOutput(BaseModel):
    """Structured output produced by the Meeting Intelligence Agent."""

    meeting_id: str = Field(..., description="Unique ID for this meeting")
    meeting_date: Optional[str] = Field(
        None, description="Date of meeting if extractable"
    )
    participants: list[str] = Field(
        default_factory=list,
        description="All participants identified in the meeting"
    )
    decisions: list[MeetingDecision] = Field(
        default_factory=list,
        description="All decisions made in the meeting"
    )
    action_items: list[ActionItem] = Field(
        default_factory=list,
        description="All action items assigned in the meeting"
    )
    key_topics: list[str] = Field(
        default_factory=list,
        description="Main topics discussed"
    )
    summary: str = Field(
        default="", description="Executive summary of the meeting"
    )
    stored_in_graph: bool = Field(
        default=False,
        description="Whether decisions were stored in Neo4j"
    )
    stored_in_vector: bool = Field(
        default=False,
        description="Whether transcript was stored in ChromaDB"
    )


class MeetingAgent(BaseAgent):
    """Capture agent that extracts structured knowledge from meeting content.

    Processes raw meeting transcripts or meeting-related emails to extract
    decisions, action items, participants, and topics. Stores extracted
    knowledge in both Neo4j (structured) and ChromaDB (semantic) for
    retrieval by the specialist agents.
    """

    def __init__(self, memory=None) -> None:
        """Initialises the MeetingAgent.

        Args:
            memory: Optional MemoryManager for dependency injection.
        """
        super().__init__(
            agent_name="MeetingAgent",
            category=QueryCategory.DECISION,
            memory=memory,
        )

    def _build_prompt(self, query: str, context: str = "") -> str:
        """Builds the meeting extraction prompt for Gemini.

        Args:
            query: The raw meeting transcript or meeting email content.
            context: Unused — kept for BaseAgent interface compliance.

        Returns:
            The complete extraction prompt string to send to Gemini.
        """
        return f"""
You are the Meeting Intelligence Agent for a Corporate Institutional Memory System.
Extract all structured knowledge from the following meeting content.

MEETING CONTENT:
{query}

Extract and return the following in EXACT format:

MEETING_DATE: <date or UNKNOWN>
PARTICIPANTS: <comma-separated list of names or emails>
SUMMARY: <2-3 sentence executive summary>

DECISIONS:
DECISION_1: <decision summary> | CONTEXT: <brief context> | PARTICIPANTS: <who decided>
DECISION_2: <decision summary> | CONTEXT: <brief context> | PARTICIPANTS: <who decided>
(add more as needed, or write NONE if no decisions)

ACTION_ITEMS:
ACTION_1: <what to do> | OWNER: <person> | DEADLINE: <date or NONE>
ACTION_2: <what to do> | OWNER: <person> | DEADLINE: <date or NONE>
(add more as needed, or write NONE if no action items)

KEY_TOPICS: <comma-separated list of main topics discussed>

Respond ONLY in the format above. No extra text.
""".strip()

    def _parse_extraction_response(
        self,
        response: str,
        meeting_id: str,
    ) -> MeetingExtractionOutput:
        """Parses the structured LLM extraction response into a MeetingExtractionOutput.

        Args:
            response: Raw LLM response string in structured format.
            meeting_id: Unique ID assigned to this meeting.

        Returns:
            A populated MeetingExtractionOutput object.
        """

        def _extract_field(pattern: str, text: str) -> Optional[str]:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            return match.group(1).strip() if match else None

        # ── Extract scalar fields ─────────────────────────────────────────────
        meeting_date = _extract_field(r"^MEETING_DATE:\s*(.+)$", response)
        if meeting_date and meeting_date.upper() == "UNKNOWN":
            meeting_date = None

        raw_participants = _extract_field(r"^PARTICIPANTS:\s*(.+)$", response)
        participants = (
            [p.strip() for p in raw_participants.split(",") if p.strip()]
            if raw_participants
            else []
        )

        summary = _extract_field(r"^SUMMARY:\s*(.+)$", response) or ""

        raw_topics = _extract_field(r"^KEY_TOPICS:\s*(.+)$", response)
        key_topics = (
            [t.strip() for t in raw_topics.split(",") if t.strip()]
            if raw_topics
            else []
        )

        # ── Extract decisions ─────────────────────────────────────────────────
        decisions: list[MeetingDecision] = []
        decision_pattern = re.compile(
            r"^DECISION_\d+:\s*(.+?)(?:\s*\|\s*CONTEXT:\s*(.+?))?(?:\s*\|\s*PARTICIPANTS:\s*(.+))?$",
            re.IGNORECASE | re.MULTILINE,
        )

        for match in decision_pattern.finditer(response):
            decision_summary = match.group(1).strip()
            if decision_summary.upper() == "NONE":
                continue

            decision_participants = []
            if match.group(3):
                decision_participants = [
                    p.strip()
                    for p in match.group(3).split(",")
                    if p.strip()
                ]

            decisions.append(
                MeetingDecision(
                    summary=decision_summary,
                    context=match.group(2).strip() if match.group(2) else "",
                    participants=decision_participants,
                )
            )

        # ── Extract action items ──────────────────────────────────────────────
        action_items: list[ActionItem] = []
        action_pattern = re.compile(
            r"^ACTION_\d+:\s*(.+?)(?:\s*\|\s*OWNER:\s*(.+?))?(?:\s*\|\s*DEADLINE:\s*(.+))?$",
            re.IGNORECASE | re.MULTILINE,
        )

        for match in action_pattern.finditer(response):
            action_desc = match.group(1).strip()
            if action_desc.upper() == "NONE":
                continue

            deadline = match.group(3).strip() if match.group(3) else None
            if deadline and deadline.upper() == "NONE":
                deadline = None

            action_items.append(
                ActionItem(
                    description=action_desc,
                    owner=match.group(2).strip() if match.group(2) else None,
                    deadline=deadline,
                )
            )

        return MeetingExtractionOutput(
            meeting_id=meeting_id,
            meeting_date=meeting_date,
            participants=participants,
            decisions=decisions,
            action_items=action_items,
            key_topics=key_topics,
            summary=summary,
        )

    def _store_in_graph(
        self,
        extraction: MeetingExtractionOutput,
        meeting_id: str,
    ) -> bool:
        """Stores extracted decisions and participants in Neo4j.

        Creates Person nodes for all participants, Decision nodes for
        all decisions, and MADE_DECISION relationships linking them.

        Args:
            extraction: The populated MeetingExtractionOutput to store.
            meeting_id: Unique meeting ID used as source reference.

        Returns:
            True if storage succeeded, False otherwise.
        """
        if not self._memory._graph_store:
            logger.warning(
                "MeetingAgent: GraphStore unavailable — skipping graph storage."
            )
            return False

        try:
            # ── Upsert participant Person nodes ───────────────────────────────
            for participant in extraction.participants:
                person = PersonNode(
                    node_id=participant.lower(),
                    name=participant,
                    email=participant.lower()
                    if "@" in participant
                    else f"{participant.lower().replace(' ', '.')}@unknown.com",
                )
                self._memory.upsert_person(person)

            # ── Upsert Decision nodes and relationships ────────────────────────
            for i, decision in enumerate(extraction.decisions):
                decision_id = f"{meeting_id}_decision_{i}"

                decision_node = DecisionNode(
                    node_id=decision_id,
                    summary=decision.summary,
                    date=datetime.utcnow() if not extraction.meeting_date else None,
                    source_message_id=meeting_id,
                )
                self._memory.upsert_decision(decision_node)

                # Link each decision participant to the decision
                for participant in decision.participants or extraction.participants:
                    participant_id = participant.lower()
                    relationship = GraphRelationship(
                        from_node_id=participant_id,
                        to_node_id=decision_id,
                        relationship_type=RelationshipType.MADE_DECISION,
                        properties={"meeting_id": meeting_id},
                    )
                    try:
                        self._memory.create_relationship(relationship)
                    except Exception as exc:
                        logger.debug(
                            "Relationship creation failed for '{}': {}",
                            participant_id,
                            exc,
                        )

            logger.info(
                "MeetingAgent stored graph data | decisions={} | participants={}",
                len(extraction.decisions),
                len(extraction.participants),
            )
            return True

        except Exception as exc:
            logger.error("MeetingAgent graph storage failed: {}", exc)
            return False

    def _store_in_vector(
        self,
        content: str,
        meeting_id: str,
        extraction: MeetingExtractionOutput,
    ) -> bool:
        """Stores meeting transcript chunks in ChromaDB for semantic retrieval.

        Directly calls the ChromaDB collection to upsert the meeting
        content as a searchable chunk with full meeting metadata.

        Args:
            content: Raw meeting transcript or email content.
            meeting_id: Unique meeting ID used as chunk ID.
            extraction: Populated extraction output for metadata.

        Returns:
            True if storage succeeded, False otherwise.
        """
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            from sentence_transformers import SentenceTransformer

            client = chromadb.PersistentClient(
                path=settings.chromadb.persist_directory,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            collection = client.get_or_create_collection(
                name=settings.chromadb.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

            model = SentenceTransformer(settings.chromadb.embedding_model)
            embedding = model.encode(content[:1000], convert_to_numpy=True).tolist()

            collection.upsert(
                ids=[meeting_id],
                documents=[content[:1000]],
                embeddings=[embedding],
                metadatas=[{
                    "message_id": meeting_id,
                    "chunk_index": 0,
                    "sender": "meeting_agent",
                    "receiver": ",".join(extraction.participants[:5]),
                    "subject": f"Meeting: {', '.join(extraction.key_topics[:3])}",
                    "date": extraction.meeting_date or datetime.utcnow().isoformat(),
                    "word_count": len(content.split()),
                    "department": "Meeting",
                }],
            )

            logger.info(
                "MeetingAgent stored transcript in ChromaDB | id='{}'",
                meeting_id,
            )
            return True

        except Exception as exc:
            logger.error("MeetingAgent vector storage failed: {}", exc)
            return False

    def extract_from_content(self, content: str) -> MeetingExtractionOutput:
        """Extracts structured meeting knowledge from raw content.

        This is the primary public method called directly by the
        Capture Orchestrator for meeting transcript processing.

        Args:
            content: Raw meeting transcript or meeting-related email text.

        Returns:
            A fully populated MeetingExtractionOutput with all
            extracted knowledge and storage status flags.
        """
        meeting_id = f"meeting_{uuid.uuid4().hex[:12]}"

        logger.info(
            "MeetingAgent extracting | meeting_id='{}'", meeting_id
        )

        # ── Phase 2: LLM extraction ───────────────────────────────────────────
        prompt = self._build_prompt(content)

        try:
            raw_response = self._invoke_llm(prompt)
        except RuntimeError as exc:
            logger.error("MeetingAgent LLM extraction failed: {}", exc)
            return MeetingExtractionOutput(
                meeting_id=meeting_id,
                summary=f"Extraction failed: {exc}",
            )

        # ── Phase 3: Parse response ───────────────────────────────────────────
        extraction = self._parse_extraction_response(raw_response, meeting_id)

        # ── Phase 4: Store in Neo4j ───────────────────────────────────────────
        extraction.stored_in_graph = self._store_in_graph(
            extraction, meeting_id
        )

        # ── Phase 5: Store in ChromaDB ────────────────────────────────────────
        extraction.stored_in_vector = self._store_in_vector(
            content, meeting_id, extraction
        )

        logger.info(
            "MeetingAgent complete | meeting_id='{}' | decisions={} | "
            "actions={} | graph={} | vector={}",
            meeting_id,
            len(extraction.decisions),
            len(extraction.action_items),
            extraction.stored_in_graph,
            extraction.stored_in_vector,
        )

        return extraction

    def run(self, agent_input: AgentInput) -> AgentOutput:
        """Implements BaseAgent.run() for orchestrator compatibility.

        Treats the query field of AgentInput as raw meeting content
        to process through the extraction pipeline.

        Args:
            agent_input: Standard AgentInput where query contains
                the raw meeting transcript or email content.

        Returns:
            AgentOutput where answer contains the meeting summary
            and follow_up_questions lists the action items.
        """
        if not agent_input.query or len(agent_input.query.strip()) < 20:
            return self._build_output(
                query=agent_input.query,
                answer="Meeting content is too short to extract meaningful intelligence.",
                sources=[],
                status=AgentStatus.PARTIAL,
                confidence=0.0,
            )

        extraction = self.extract_from_content(agent_input.query)

        # Format action items as follow-up questions
        follow_ups = [
            f"{item.owner or 'Unassigned'}: {item.description}"
            + (f" (Due: {item.deadline})" if item.deadline else "")
            for item in extraction.action_items[:3]
        ]

        answer = (
            f"{extraction.summary}\n\n"
            f"Decisions Made : {len(extraction.decisions)}\n"
            f"Action Items   : {len(extraction.action_items)}\n"
            f"Participants   : {', '.join(extraction.participants[:5])}\n"
            f"Key Topics     : {', '.join(extraction.key_topics[:5])}\n"
            f"Stored in Graph: {extraction.stored_in_graph}\n"
            f"Stored in Vector: {extraction.stored_in_vector}"
        )

        return self._build_output(
            query=agent_input.query[:100],
            answer=answer,
            sources=[],
            status=AgentStatus.SUCCESS,
            confidence=0.9 if extraction.decisions else 0.5,
            follow_up_questions=follow_ups,
        )