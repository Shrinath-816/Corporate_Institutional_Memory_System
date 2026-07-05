"""
Module: schemas/query_schema.py

Purpose:
    Pydantic models for all API request and response payloads related
    to user queries entering the system through the FastAPI layer.

Responsibilities:
    - Define the incoming query request model validated at the API boundary.
    - Define the outgoing query response model returned to the client.
    - Define the health check response model.
    - Act as the contract between the UI/client and the backend API.

Workflow:
    HTTP Request → QueryRequest (validated) → Orchestrator → QueryResponse → HTTP Response
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from schemas.agent_schema import AgentOutput, QueryCategory


class QueryRequest(BaseModel):
    """Represents an incoming user query submitted via the API.

    This model is validated at the FastAPI route boundary before
    being forwarded to the Master Orchestrator.
    """

    query: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The user's natural language question"
    )
    session_id: Optional[str] = Field(
        None,
        description="Optional session ID for maintaining conversational context"
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of source documents to retrieve"
    )
    category_hint: Optional[QueryCategory] = Field(
        None,
        description="Optional category hint to bypass router classification"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "Why did Enron stop the California energy trading operations?",
                "session_id": "session-abc-123",
                "top_k": 5
            }
        }
    }


class QueryResponse(BaseModel):
    """Represents the complete response returned to the client after query processing.

    Wraps the AgentOutput with additional API-level metadata such as
    processing time and request tracing information.
    """

    request_id: str = Field(..., description="Unique identifier for this request")
    query: str = Field(..., description="Original query from the user")
    result: AgentOutput = Field(..., description="The agent's full output")
    processing_time_ms: float = Field(
        ..., description="Total end-to-end processing time in milliseconds"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this response was generated"
    )


class HealthResponse(BaseModel):
    """Response model for the system health check endpoint.

    Reports the operational status of each subsystem dependency.
    """

    status: str = Field(..., description="Overall system status: healthy or degraded")
    version: str = Field(..., description="Application version string")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    dependencies: dict[str, str] = Field(
        default_factory=dict,
        description="Status of each dependency: chromadb, neo4j, gemini"
    )