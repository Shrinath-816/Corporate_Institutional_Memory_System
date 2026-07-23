"""
Module: orchestrators/capture_orchestrator.py

Purpose:
    Orchestrates all knowledge capture agents to ingest new knowledge
    into the institutional memory system from various content sources.

Responsibilities:
    - Route incoming content to the correct capture agent based on type.
    - Coordinate MeetingAgent, PostMortemAgent, and TribalKnowledgeAgent.
    - Accept raw content with a content type indicator.
    - Return a unified CaptureResult summarising what was stored.
    - Handle failures per agent without aborting the entire capture flow.

Workflow:
    Phase 1 — Receive CaptureRequest with content and content type.
    Phase 2 — Route to the appropriate capture agent.
    Phase 3 — Execute the capture agent and collect output.
    Phase 4 — Return a structured CaptureResult.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from agents.capture.meeting_agent import MeetingAgent
from agents.capture.postmortem_agent import PostMortemAgent
from agents.capture.tribal_knowledge_agent import (
    TribalKnowledgeAgent,
    ExpertProfile,
)
from memory.memory_manager import MemoryManager, memory_manager
from schemas.agent_schema import AgentInput


# ── Content Type Enumeration ─────────────────────────────────────────────────

class ContentType(str, Enum):
    """Defines the type of content being submitted for capture."""

    MEETING_TRANSCRIPT = "meeting_transcript"
    POST_MORTEM = "post_mortem"
    TRIBAL_KNOWLEDGE = "tribal_knowledge"


# ── Capture Request & Result Models ─────────────────────────────────────────

class CaptureRequest(BaseModel):
    """Input model for a knowledge capture request.

    Attributes:
        content: Raw text content to be captured.
        content_type: Type of content determining which agent handles it.
        expert_profile: Required when content_type is TRIBAL_KNOWLEDGE.
        session_id: Optional session ID for tracing.
    """

    content: str = Field(
        ..., min_length=20,
        description="Raw content to capture into institutional memory"
    )
    content_type: ContentType = Field(
        ..., description="Type of content being submitted"
    )
    expert_profile: Optional[ExpertProfile] = Field(
        None,
        description="Expert profile required for tribal knowledge capture"
    )
    session_id: Optional[str] = Field(
        None, description="Optional session ID for tracing"
    )


class CaptureResult(BaseModel):
    """Structured result returned after a knowledge capture operation."""

    session_id: Optional[str] = Field(None)
    content_type: ContentType = Field(...)
    agent_used: str = Field(..., description="Name of capture agent used")
    success: bool = Field(..., description="Whether capture succeeded")
    summary: str = Field(..., description="Summary of captured knowledge")
    items_captured: int = Field(
        default=0, description="Number of insights/decisions captured"
    )
    stored_in_graph: bool = Field(default=False)
    stored_in_vector: bool = Field(default=False)
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    error: Optional[str] = Field(
        None, description="Error message if capture failed"
    )


class CaptureOrchestrator:
    """Orchestrates all knowledge capture agents.

    Routes incoming content to the correct capture agent based on
    content type, executes the capture, and returns a unified result.

    Attributes:
        _meeting_agent: Handles meeting transcript capture.
        _postmortem_agent: Handles post-mortem capture.
        _tribal_agent: Handles tribal knowledge capture.
    """

    def __init__(
        self,
        memory: Optional[MemoryManager] = None,
    ) -> None:
        """Initialises the CaptureOrchestrator with all capture agents.

        Args:
            memory: Optional MemoryManager for dependency injection.
        """
        mem = memory or memory_manager

        self._meeting_agent = MeetingAgent(memory=mem)
        self._postmortem_agent = PostMortemAgent(memory=mem)
        self._tribal_agent = TribalKnowledgeAgent(memory=mem)

        logger.info("CaptureOrchestrator initialised.")

    # ── Private Route Handlers ───────────────────────────────────────────────

    def _capture_meeting(self, request: CaptureRequest) -> CaptureResult:
        """Routes content to MeetingAgent and returns a CaptureResult.

        Args:
            request: The incoming CaptureRequest.

        Returns:
            A populated CaptureResult from meeting capture.
        """
        try:
            output = self._meeting_agent.extract_from_content(
                request.content
            )

            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used=self._meeting_agent.agent_name,
                success=True,
                summary=output.summary or "Meeting captured successfully.",
                items_captured=(
                    len(output.decisions) + len(output.action_items)
                ),
                stored_in_graph=output.stored_in_graph,
                stored_in_vector=output.stored_in_vector,
            )

        except Exception as exc:
            logger.error("Meeting capture failed: {}", exc)
            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used=self._meeting_agent.agent_name,
                success=False,
                summary="Meeting capture failed.",
                error=str(exc),
            )

    def _capture_postmortem(self, request: CaptureRequest) -> CaptureResult:
        """Routes content to PostMortemAgent and returns a CaptureResult.

        Args:
            request: The incoming CaptureRequest.

        Returns:
            A populated CaptureResult from post-mortem capture.
        """
        try:
            output = self._postmortem_agent.extract_from_content(
                request.content
            )

            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used=self._postmortem_agent.agent_name,
                success=True,
                summary=output.summary or "Post-mortem captured successfully.",
                items_captured=(
                    len(output.lessons_learned) + len(output.recommendations)
                ),
                stored_in_graph=output.stored_in_graph,
                stored_in_vector=output.stored_in_vector,
            )

        except Exception as exc:
            logger.error("Post-mortem capture failed: {}", exc)
            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used=self._postmortem_agent.agent_name,
                success=False,
                summary="Post-mortem capture failed.",
                error=str(exc),
            )

    def _capture_tribal_knowledge(
        self, request: CaptureRequest
    ) -> CaptureResult:
        """Routes content to TribalKnowledgeAgent and returns a CaptureResult.

        Args:
            request: The incoming CaptureRequest with expert_profile set.

        Returns:
            A populated CaptureResult from tribal knowledge capture.
        """
        if not request.expert_profile:
            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used=self._tribal_agent.agent_name,
                success=False,
                summary="Tribal knowledge capture requires an expert profile.",
                error="expert_profile is required for TRIBAL_KNOWLEDGE content type.",
            )

        try:
            output = self._tribal_agent.conduct_interview(
                profile=request.expert_profile,
                interview_responses=request.content,
            )

            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used=self._tribal_agent.agent_name,
                success=True,
                summary=output.summary or "Tribal knowledge captured successfully.",
                items_captured=len(output.insights_captured),
                stored_in_graph=output.stored_in_graph,
                stored_in_vector=output.stored_in_vector,
            )

        except Exception as exc:
            logger.error("Tribal knowledge capture failed: {}", exc)
            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used=self._tribal_agent.agent_name,
                success=False,
                summary="Tribal knowledge capture failed.",
                error=str(exc),
            )

    # ── Public Entry Point ───────────────────────────────────────────────────

    def capture(self, request: CaptureRequest) -> CaptureResult:
        """Routes a capture request to the appropriate agent.

        This is the single public entry point for all knowledge capture
        operations. Selects the correct agent based on content type and
        returns a unified CaptureResult.

        Args:
            request: A validated CaptureRequest with content and type.

        Returns:
            A CaptureResult summarising the capture operation.
        """
        logger.info(
            "CaptureOrchestrator routing | type='{}' | content_length={}",
            request.content_type.value,
            len(request.content),
        )

        route_map = {
            ContentType.MEETING_TRANSCRIPT: self._capture_meeting,
            ContentType.POST_MORTEM: self._capture_postmortem,
            ContentType.TRIBAL_KNOWLEDGE: self._capture_tribal_knowledge,
        }

        handler = route_map.get(request.content_type)

        if not handler:
            logger.error(
                "No handler for content type: '{}'",
                request.content_type,
            )
            return CaptureResult(
                session_id=request.session_id,
                content_type=request.content_type,
                agent_used="None",
                success=False,
                summary="Unsupported content type.",
                error=f"No handler registered for '{request.content_type}'.",
            )

        result = handler(request)

        logger.info(
            "CaptureOrchestrator complete | type='{}' | success={} | "
            "items={} | graph={} | vector={}",
            request.content_type.value,
            result.success,
            result.items_captured,
            result.stored_in_graph,
            result.stored_in_vector,
        )

        return result