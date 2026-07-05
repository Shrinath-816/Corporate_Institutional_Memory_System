"""
Module: schemas/memory_schema.py

Purpose:
    Pydantic models representing objects stored in and retrieved from
    both the ChromaDB vector store and the Neo4j graph database.

Responsibilities:
    - Define the VectorSearchResult returned by ChromaDB queries.
    - Define graph node models for Person, Decision, Project, and Policy.
    - Define graph relationship models linking nodes in Neo4j.
    - Define the KnowledgeGap model produced by the Audit Orchestrator.

Workflow:
    ChromaDB query → VectorSearchResult
    Neo4j query    → GraphNode subclasses + GraphRelationship
    Audit agent    → KnowledgeGap
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Vector Store Models ──────────────────────────────────────────────────────

class VectorSearchResult(BaseModel):
    """Represents a single result returned from a ChromaDB similarity search.

    Used by all retrieval agents to process and rank retrieved documents
    before passing them to the LLM for answer synthesis.
    """

    chunk_id: str = Field(..., description="ChromaDB document ID")
    text: str = Field(..., description="The retrieved chunk text")
    distance: float = Field(..., description="Cosine distance score (lower = more similar)")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="All metadata stored alongside this chunk"
    )

    @property
    def relevance_score(self) -> float:
        """Converts cosine distance to a 0-1 relevance score.

        Returns:
            Float between 0.0 (irrelevant) and 1.0 (identical).
        """
        return round(1.0 - self.distance, 4)


# ── Graph Node Models ────────────────────────────────────────────────────────

class NodeType(str, Enum):
    """Enumeration of all node types stored in the Neo4j knowledge graph."""

    PERSON = "Person"
    DECISION = "Decision"
    PROJECT = "Project"
    POLICY = "Policy"
    DEPARTMENT = "Department"
    EMAIL = "Email"


class PersonNode(BaseModel):
    """Represents a Person node in the Neo4j knowledge graph.

    Each unique email sender/receiver becomes a Person node, enabling
    relationship mapping between people, decisions, and projects.
    """

    node_id: str = Field(..., description="Unique node identifier (email address)")
    name: str = Field(..., description="Full name of the person")
    email: str = Field(..., description="Email address (primary identifier)")
    department: Optional[str] = Field(None, description="Inferred department")
    role: Optional[str] = Field(None, description="Inferred job role/title")
    node_type: NodeType = Field(default=NodeType.PERSON)


class DecisionNode(BaseModel):
    """Represents a Decision node in the Neo4j knowledge graph.

    Captures key decisions extracted from email communications, linking
    them to the people involved and the context in which they were made.
    """

    node_id: str = Field(..., description="Unique decision identifier")
    summary: str = Field(..., description="Brief summary of the decision made")
    date: Optional[datetime] = Field(None, description="When the decision was made")
    source_message_id: str = Field(..., description="Email message ID this was extracted from")
    department: Optional[str] = Field(None, description="Department that made this decision")
    node_type: NodeType = Field(default=NodeType.DECISION)


class ProjectNode(BaseModel):
    """Represents a Project node in the Neo4j knowledge graph."""

    node_id: str = Field(..., description="Unique project identifier")
    name: str = Field(..., description="Project name")
    status: Optional[str] = Field(None, description="Project status: active, completed, cancelled")
    start_date: Optional[datetime] = Field(None)
    end_date: Optional[datetime] = Field(None)
    node_type: NodeType = Field(default=NodeType.PROJECT)


class PolicyNode(BaseModel):
    """Represents a Policy node in the Neo4j knowledge graph."""

    node_id: str = Field(..., description="Unique policy identifier")
    title: str = Field(..., description="Policy title")
    content: str = Field(..., description="Full policy text")
    effective_date: Optional[datetime] = Field(None)
    last_updated: Optional[datetime] = Field(None)
    node_type: NodeType = Field(default=NodeType.POLICY)


# ── Graph Relationship Models ────────────────────────────────────────────────

class RelationshipType(str, Enum):
    """Enumeration of all edge/relationship types in the Neo4j graph."""

    MADE_DECISION = "MADE_DECISION"
    INVOLVED_IN = "INVOLVED_IN"
    PART_OF = "PART_OF"
    REPORTED_TO = "REPORTED_TO"
    COMMUNICATED_WITH = "COMMUNICATED_WITH"
    OWNS_POLICY = "OWNS_POLICY"


class GraphRelationship(BaseModel):
    """Represents a directed relationship (edge) between two nodes in Neo4j.

    Models the connection between any two entities in the knowledge graph,
    such as a Person who MADE_DECISION about a Project.
    """

    from_node_id: str = Field(..., description="Source node ID")
    to_node_id: str = Field(..., description="Target node ID")
    relationship_type: RelationshipType = Field(..., description="Type of relationship")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional properties on this relationship edge"
    )


# ── Audit Models ─────────────────────────────────────────────────────────────

class KnowledgeGapSeverity(str, Enum):
    """Severity levels for knowledge gaps detected by the Audit Orchestrator."""

    CRITICAL = "CRITICAL"     # Key person or department with no documentation
    HIGH = "HIGH"             # Significant topic with sparse coverage
    MEDIUM = "MEDIUM"         # Minor gaps that should be addressed
    LOW = "LOW"               # Informational only


class KnowledgeGap(BaseModel):
    """Represents a gap in institutional knowledge detected by the Audit Agent.

    Produced by the Gap Detector Agent and the Single Point of Failure Agent
    to surface risks in the knowledge base to system administrators.
    """

    gap_id: str = Field(..., description="Unique identifier for this knowledge gap")
    description: str = Field(..., description="Human-readable description of the gap")
    affected_area: str = Field(
        ..., description="Department, person, or topic where the gap exists"
    )
    severity: KnowledgeGapSeverity = Field(..., description="Severity level of this gap")
    recommended_action: str = Field(
        ..., description="Suggested action to close this knowledge gap"
    )
    detected_at: datetime = Field(default_factory=datetime.utcnow)