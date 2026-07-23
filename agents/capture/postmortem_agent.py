"""
Module: agents/capture/postmortem_agent.py

Purpose:
    Extracts and stores structured knowledge from project post-mortem
    reports and retrospective discussions into the institutional memory.

Responsibilities:
    - Accept raw post-mortem text, retrospective emails, or project
      closure documents as input.
    - Use Gemini to extract structured post-mortem intelligence:
      what worked, what failed, root causes, lessons learned, and
      recommendations.
    - Store extracted Project and Decision nodes in Neo4j.
    - Store post-mortem content in ChromaDB for semantic retrieval.
    - Return a structured PostMortemExtractionOutput with all findings.

Workflow:
    Phase 1 — Receive raw post-mortem content via AgentInput.
    Phase 2 — Use Gemini to extract structured post-mortem data.
    Phase 3 — Parse LLM response into PostMortemExtractionOutput.
    Phase 4 — Store Project node and lessons in Neo4j.
    Phase 5 — Store post-mortem chunks in ChromaDB.
    Phase 6 — Return PostMortemExtractionOutput with storage status.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

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
from schemas.memory_schema import (
    ProjectNode,
    DecisionNode,
    PersonNode,
    GraphRelationship,
    RelationshipType,
)


# ── Post-Mortem Data Models ──────────────────────────────────────────────────

class LessonLearned(BaseModel):
    """Represents a single lesson learned from a project post-mortem."""

    category: str = Field(
        ..., description="Category: PROCESS, TECHNICAL, COMMUNICATION, or OTHER"
    )
    description: str = Field(..., description="Description of the lesson")
    recommendation: str = Field(
        ..., description="Recommended action to apply this lesson"
    )


class PostMortemExtractionOutput(BaseModel):
    """Structured output produced by the Post-Mortem Agent."""

    postmortem_id: str = Field(
        ..., description="Unique ID for this post-mortem"
    )
    project_name: str = Field(
        default="Unknown Project",
        description="Name of the project reviewed"
    )
    project_outcome: str = Field(
        default="UNKNOWN",
        description="Outcome: SUCCESS, PARTIAL_SUCCESS, FAILURE, or CANCELLED"
    )
    completion_date: Optional[str] = Field(
        None, description="Project completion date if available"
    )
    participants: list[str] = Field(
        default_factory=list,
        description="People who participated in the post-mortem"
    )
    what_worked: list[str] = Field(
        default_factory=list,
        description="Things that went well during the project"
    )
    what_failed: list[str] = Field(
        default_factory=list,
        description="Things that went wrong during the project"
    )
    root_causes: list[str] = Field(
        default_factory=list,
        description="Root causes identified for failures"
    )
    lessons_learned: list[LessonLearned] = Field(
        default_factory=list,
        description="Structured lessons learned with recommendations"
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Specific recommendations for future projects"
    )
    summary: str = Field(
        default="", description="Executive summary of the post-mortem"
    )
    stored_in_graph: bool = Field(
        default=False,
        description="Whether data was stored in Neo4j"
    )
    stored_in_vector: bool = Field(
        default=False,
        description="Whether content was stored in ChromaDB"
    )


class PostMortemAgent(BaseAgent):
    """Capture agent that extracts structured knowledge from post-mortems.

    Processes raw project retrospective content to extract what worked,
    what failed, root causes, and lessons learned. Stores all findings
    in both Neo4j (structured project knowledge) and ChromaDB (semantic
    retrieval) to enrich the institutional memory permanently.
    """

    def __init__(self, memory=None) -> None:
        """Initialises the PostMortemAgent.

        Args:
            memory: Optional MemoryManager for dependency injection.
        """
        super().__init__(
            agent_name="PostMortemAgent",
            category=QueryCategory.PROJECT,
            memory=memory,
        )

    def _build_prompt(self, query: str, context: str = "") -> str:
        """Builds the post-mortem extraction prompt for Gemini.

        Args:
            query: Raw post-mortem text or retrospective content.
            context: Unused — kept for BaseAgent interface compliance.

        Returns:
            The complete extraction prompt string to send to Gemini.
        """
        return f"""
You are the Post-Mortem Intelligence Agent for a Corporate Institutional Memory System.
Extract all structured knowledge from the following project post-mortem content.

POST-MORTEM CONTENT:
{query}

Extract and return in EXACT format:

PROJECT_NAME: <name or UNKNOWN>
PROJECT_OUTCOME: <SUCCESS | PARTIAL_SUCCESS | FAILURE | CANCELLED>
COMPLETION_DATE: <date or UNKNOWN>
PARTICIPANTS: <comma-separated names or emails>
SUMMARY: <2-3 sentence executive summary>

WHAT_WORKED:
WORKED_1: <what went well>
WORKED_2: <what went well>
(add more as needed or write NONE)

WHAT_FAILED:
FAILED_1: <what went wrong>
FAILED_2: <what went wrong>
(add more as needed or write NONE)

ROOT_CAUSES:
CAUSE_1: <root cause identified>
CAUSE_2: <root cause identified>
(add more as needed or write NONE)

LESSONS_LEARNED:
LESSON_1: CATEGORY: <PROCESS|TECHNICAL|COMMUNICATION|OTHER> | DESCRIPTION: <lesson> | RECOMMENDATION: <action>
LESSON_2: CATEGORY: <PROCESS|TECHNICAL|COMMUNICATION|OTHER> | DESCRIPTION: <lesson> | RECOMMENDATION: <action>
(add more as needed or write NONE)

RECOMMENDATIONS:
REC_1: <specific recommendation>
REC_2: <specific recommendation>
(add more as needed or write NONE)

Respond ONLY in the format above. No extra text.
""".strip()

    def _parse_list_items(
        self,
        response: str,
        prefix: str,
    ) -> list[str]:
        """Extracts a list of items matching a numbered prefix pattern.

        Args:
            response: The full LLM response string.
            prefix: The item prefix to match e.g. 'WORKED', 'FAILED'.

        Returns:
            List of extracted string values for the given prefix.
        """
        pattern = re.compile(
            rf"^{prefix}_\d+:\s*(.+)$",
            re.IGNORECASE | re.MULTILINE,
        )
        items = [
            m.strip()
            for m in pattern.findall(response)
            if m.strip().upper() != "NONE"
        ]
        return items

    def _parse_lessons(self, response: str) -> list[LessonLearned]:
        """Extracts structured LessonLearned objects from LLM response.

        Args:
            response: The full LLM response string.

        Returns:
            List of LessonLearned objects parsed from LESSON_N blocks.
        """
        pattern = re.compile(
            r"^LESSON_\d+:\s*CATEGORY:\s*(\w+)\s*\|\s*"
            r"DESCRIPTION:\s*(.+?)\s*\|\s*RECOMMENDATION:\s*(.+)$",
            re.IGNORECASE | re.MULTILINE,
        )

        lessons: list[LessonLearned] = []
        for match in pattern.finditer(response):
            category = match.group(1).strip().upper()
            description = match.group(2).strip()
            recommendation = match.group(3).strip()

            if description.upper() == "NONE":
                continue

            valid_categories = {
                "PROCESS", "TECHNICAL", "COMMUNICATION", "OTHER"
            }
            if category not in valid_categories:
                category = "OTHER"

            lessons.append(
                LessonLearned(
                    category=category,
                    description=description,
                    recommendation=recommendation,
                )
            )

        return lessons

    def _parse_extraction_response(
        self,
        response: str,
        postmortem_id: str,
    ) -> PostMortemExtractionOutput:
        """Parses the structured LLM response into a PostMortemExtractionOutput.

        Args:
            response: Raw LLM response string in structured format.
            postmortem_id: Unique ID assigned to this post-mortem.

        Returns:
            A populated PostMortemExtractionOutput object.
        """
        def _extract_field(pattern: str, text: str) -> Optional[str]:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            return match.group(1).strip() if match else None

        # ── Scalar fields ─────────────────────────────────────────────────────
        project_name = (
            _extract_field(r"^PROJECT_NAME:\s*(.+)$", response)
            or "Unknown Project"
        )
        if project_name.upper() == "UNKNOWN":
            project_name = "Unknown Project"

        raw_outcome = _extract_field(r"^PROJECT_OUTCOME:\s*(\w+)", response)
        valid_outcomes = {
            "SUCCESS", "PARTIAL_SUCCESS", "FAILURE", "CANCELLED"
        }
        project_outcome = (
            raw_outcome.upper()
            if raw_outcome and raw_outcome.upper() in valid_outcomes
            else "UNKNOWN"
        )

        completion_date = _extract_field(
            r"^COMPLETION_DATE:\s*(.+)$", response
        )
        if completion_date and completion_date.upper() == "UNKNOWN":
            completion_date = None

        raw_participants = _extract_field(
            r"^PARTICIPANTS:\s*(.+)$", response
        )
        participants = (
            [p.strip() for p in raw_participants.split(",") if p.strip()]
            if raw_participants
            else []
        )

        summary = _extract_field(r"^SUMMARY:\s*(.+)$", response) or ""

        # ── List fields ───────────────────────────────────────────────────────
        what_worked = self._parse_list_items(response, "WORKED")
        what_failed = self._parse_list_items(response, "FAILED")
        root_causes = self._parse_list_items(response, "CAUSE")
        recommendations = self._parse_list_items(response, "REC")
        lessons_learned = self._parse_lessons(response)

        return PostMortemExtractionOutput(
            postmortem_id=postmortem_id,
            project_name=project_name,
            project_outcome=project_outcome,
            completion_date=completion_date,
            participants=participants,
            what_worked=what_worked,
            what_failed=what_failed,
            root_causes=root_causes,
            lessons_learned=lessons_learned,
            recommendations=recommendations,
            summary=summary,
        )

    def _store_in_graph(
        self,
        extraction: PostMortemExtractionOutput,
        postmortem_id: str,
    ) -> bool:
        """Stores extracted post-mortem data in Neo4j graph.

        Creates a Project node, participant Person nodes, and Decision
        nodes for each lesson learned with INVOLVED_IN relationships.

        Args:
            extraction: The populated PostMortemExtractionOutput.
            postmortem_id: Unique post-mortem ID for reference.

        Returns:
            True if storage succeeded, False otherwise.
        """
        if not self._memory._graph_store:
            logger.warning(
                "PostMortemAgent: GraphStore unavailable — skipping."
            )
            return False

        try:
            # ── Upsert Project node ───────────────────────────────────────────
            project = ProjectNode(
                node_id=postmortem_id,
                name=extraction.project_name,
                status=extraction.project_outcome.lower(),
                end_date=(
                    datetime.fromisoformat(extraction.completion_date)
                    if extraction.completion_date
                    else None
                ),
            )
            self._memory.upsert_project(project)

            # ── Upsert participant Person nodes ───────────────────────────────
            for participant in extraction.participants:
                person = PersonNode(
                    node_id=participant.lower(),
                    name=participant,
                    email=(
                        participant.lower()
                        if "@" in participant
                        else f"{participant.lower().replace(' ', '.')}@unknown.com"
                    ),
                )
                self._memory.upsert_person(person)

                # Link participant to project
                relationship = GraphRelationship(
                    from_node_id=participant.lower(),
                    to_node_id=postmortem_id,
                    relationship_type=RelationshipType.INVOLVED_IN,
                    properties={
                        "role": "post_mortem_participant",
                        "postmortem_id": postmortem_id,
                    },
                )
                try:
                    self._memory.create_relationship(relationship)
                except Exception as exc:
                    logger.debug(
                        "Relationship creation failed for '{}': {}",
                        participant,
                        exc,
                    )

            # ── Store lessons as Decision nodes ───────────────────────────────
            for i, lesson in enumerate(extraction.lessons_learned):
                lesson_id = f"{postmortem_id}_lesson_{i}"
                decision = DecisionNode(
                    node_id=lesson_id,
                    summary=f"[{lesson.category}] {lesson.description}",
                    source_message_id=postmortem_id,
                    department=extraction.project_name,
                )
                self._memory.upsert_decision(decision)

            logger.info(
                "PostMortemAgent stored graph | project='{}' | "
                "participants={} | lessons={}",
                extraction.project_name,
                len(extraction.participants),
                len(extraction.lessons_learned),
            )
            return True

        except Exception as exc:
            logger.error("PostMortemAgent graph storage failed: {}", exc)
            return False

    def _store_in_vector(
        self,
        content: str,
        postmortem_id: str,
        extraction: PostMortemExtractionOutput,
    ) -> bool:
        """Stores post-mortem content in ChromaDB for semantic retrieval.

        Args:
            content: Raw post-mortem text content.
            postmortem_id: Unique post-mortem ID.
            extraction: Populated extraction for metadata.

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

            # Build rich searchable text from extracted knowledge
            searchable_text = (
                f"Project: {extraction.project_name}\n"
                f"Outcome: {extraction.project_outcome}\n"
                f"Summary: {extraction.summary}\n"
                f"What Worked: {' | '.join(extraction.what_worked[:3])}\n"
                f"What Failed: {' | '.join(extraction.what_failed[:3])}\n"
                f"Lessons: {' | '.join(l.description for l in extraction.lessons_learned[:3])}\n"
                f"Recommendations: {' | '.join(extraction.recommendations[:3])}"
            )

            model = SentenceTransformer(settings.chromadb.embedding_model)
            embedding = model.encode(
                searchable_text, convert_to_numpy=True
            ).tolist()

            collection.upsert(
                ids=[postmortem_id],
                documents=[searchable_text],
                embeddings=[embedding],
                metadatas=[{
                    "message_id": postmortem_id,
                    "chunk_index": 0,
                    "sender": "postmortem_agent",
                    "receiver": ",".join(extraction.participants[:5]),
                    "subject": f"Post-Mortem: {extraction.project_name}",
                    "date": (
                        extraction.completion_date
                        or datetime.utcnow().isoformat()
                    ),
                    "word_count": len(searchable_text.split()),
                    "department": "Post-Mortem",
                }],
            )

            logger.info(
                "PostMortemAgent stored vector | project='{}' | id='{}'",
                extraction.project_name,
                postmortem_id,
            )
            return True

        except Exception as exc:
            logger.error("PostMortemAgent vector storage failed: {}", exc)
            return False

    def extract_from_content(
        self, content: str
    ) -> PostMortemExtractionOutput:
        """Extracts structured post-mortem knowledge from raw content.

        This is the primary public method called directly by the
        Capture Orchestrator for post-mortem processing.

        Args:
            content: Raw post-mortem text, retrospective email, or
                project closure document content.

        Returns:
            A fully populated PostMortemExtractionOutput with all
            extracted knowledge and storage status flags.
        """
        postmortem_id = f"postmortem_{uuid.uuid4().hex[:12]}"

        logger.info(
            "PostMortemAgent extracting | id='{}'", postmortem_id
        )

        # ── Phase 2: LLM extraction ───────────────────────────────────────────
        prompt = self._build_prompt(content)

        try:
            raw_response = self._invoke_llm(prompt)
        except RuntimeError as exc:
            logger.error("PostMortemAgent LLM extraction failed: {}", exc)
            return PostMortemExtractionOutput(
                postmortem_id=postmortem_id,
                summary=f"Extraction failed: {exc}",
            )

        # ── Phase 3: Parse response ───────────────────────────────────────────
        extraction = self._parse_extraction_response(
            raw_response, postmortem_id
        )

        # ── Phase 4: Store in Neo4j ───────────────────────────────────────────
        extraction.stored_in_graph = self._store_in_graph(
            extraction, postmortem_id
        )

        # ── Phase 5: Store in ChromaDB ────────────────────────────────────────
        extraction.stored_in_vector = self._store_in_vector(
            content, postmortem_id, extraction
        )

        logger.info(
            "PostMortemAgent complete | project='{}' | outcome='{}' | "
            "lessons={} | graph={} | vector={}",
            extraction.project_name,
            extraction.project_outcome,
            len(extraction.lessons_learned),
            extraction.stored_in_graph,
            extraction.stored_in_vector,
        )

        return extraction

    def run(self, agent_input: AgentInput) -> AgentOutput:
        """Implements BaseAgent.run() for orchestrator compatibility.

        Treats the query field of AgentInput as raw post-mortem content.

        Args:
            agent_input: Standard AgentInput where query contains
                the raw post-mortem or retrospective content.

        Returns:
            AgentOutput where answer contains the post-mortem summary
            and follow_up_questions lists the top recommendations.
        """
        if not agent_input.query or len(agent_input.query.strip()) < 20:
            return self._build_output(
                query=agent_input.query,
                answer=(
                    "Post-mortem content is too short to extract "
                    "meaningful intelligence."
                ),
                sources=[],
                status=AgentStatus.PARTIAL,
                confidence=0.0,
            )

        extraction = self.extract_from_content(agent_input.query)

        follow_ups = extraction.recommendations[:3]

        answer = (
            f"{extraction.summary}\n\n"
            f"Project        : {extraction.project_name}\n"
            f"Outcome        : {extraction.project_outcome}\n"
            f"What Worked    : {len(extraction.what_worked)} items\n"
            f"What Failed    : {len(extraction.what_failed)} items\n"
            f"Lessons Learned: {len(extraction.lessons_learned)}\n"
            f"Recommendations: {len(extraction.recommendations)}\n"
            f"Stored in Graph: {extraction.stored_in_graph}\n"
            f"Stored in Vector: {extraction.stored_in_vector}"
        )

        return self._build_output(
            query=agent_input.query[:100],
            answer=answer,
            sources=[],
            status=AgentStatus.SUCCESS,
            confidence=(
                0.9
                if extraction.lessons_learned
                else 0.5
            ),
            follow_up_questions=follow_ups,
        )