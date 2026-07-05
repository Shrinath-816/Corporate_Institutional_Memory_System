"""
Module: schemas/agent_schema.py

Purpose:
    Pydantic models defining the input and output contracts for all agents
    in the Institutional Memory System.

Responsibilities:
    - Define a standard AgentInput accepted by every agent.
    - Define a standard AgentOutput returned by every agent.
    - Define the QueryCategory enumeration used by the Router Agent.
    - Define the Source model representing a retrieved evidence document.
    - Ensure all agent communication is type-safe and validated.

Workflow:
    User query → AgentInput → Agent processing → AgentOutput → Orchestrator
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class QueryCategory(str, Enum):
    """Enumeration of all query categories the Router Agent can classify.

    Each category maps to a dedicated specialist retrieval agent.
    """

    DECISION = "DECISION"
    PEOPLE = "PEOPLE"
    PROJECT = "PROJECT"
    POLICY = "POLICY"
    UNKNOWN = "UNKNOWN"


class AgentStatus(str, Enum):
    """Represents the execution status of an agent run."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"       # Agent returned results but with low confidence
    FAILED = "FAILED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class Source(BaseModel):
    """Represents a single retrieved evidence document backing an agent answer.

    Every claim in an AgentOutput should be traceable to one or more Sources.
    """

    document_id: str = Field(..., description="ChromaDB chunk ID of the source")
    message_id: str = Field(..., description="Parent email message ID")
    sender: str = Field(..., description="Email sender")
    date: str = Field(..., description="Email date in ISO format")
    subject: str = Field(default="", description="Email subject")
    excerpt: str = Field(
        ..., description="Relevant excerpt from the source document"
    )
    relevance_score: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Cosine similarity score from vector retrieval"
    )


class AgentInput(BaseModel):
    """Standard input contract accepted by every agent in the system.

    The orchestrator constructs this model before dispatching to any agent,
    ensuring a uniform interface across all agent types.
    """

    query: str = Field(..., min_length=3, description="User's original query text")
    category: Optional[QueryCategory] = Field(
        None, description="Pre-classified category from the Router Agent"
    )
    session_id: Optional[str] = Field(
        None, description="Conversation session ID for multi-turn memory"
    )
    top_k: int = Field(
        default=5, ge=1, le=20,
        description="Number of documents to retrieve from vector store"
    )
    metadata_filter: Optional[dict[str, Any]] = Field(
        None, description="Optional ChromaDB metadata filters (e.g. sender, date range)"
    )


class AgentOutput(BaseModel):
    """Standard output contract returned by every agent in the system.

    Orchestrators and the API layer depend on this schema for consistent
    downstream processing regardless of which agent produced the response.
    """

    agent_name: str = Field(..., description="Name of the agent that produced this output")
    query: str = Field(..., description="Original query this output answers")
    answer: str = Field(..., description="Agent's synthesised natural language answer")
    sources: list[Source] = Field(
        default_factory=list,
        description="Evidence documents used to construct the answer"
    )
    category: Optional[QueryCategory] = Field(
        None, description="Query category this answer addresses"
    )
    status: AgentStatus = Field(
        default=AgentStatus.SUCCESS,
        description="Execution status of this agent run"
    )
    confidence: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Agent's self-assessed confidence score (0.0 - 1.0)"
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="Suggested follow-up questions the user might ask"
    )