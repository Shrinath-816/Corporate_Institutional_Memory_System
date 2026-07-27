"""
Module: tests/conftest.py

Purpose:
    Shared pytest fixtures and configuration used across all unit and
    integration tests in the Institutional Memory System test suite.

Responsibilities:
    - Provide mock MemoryManager, VectorStore, and GraphStore fixtures
      so agent and orchestrator tests never touch real ChromaDB/Neo4j.
    - Provide sample domain objects (emails, chunks, agent outputs) for
      reuse across test modules.
    - Configure pytest-asyncio and common test environment settings.

Workflow:
    Fixtures defined here are automatically discovered by pytest and
    injected into any test function that declares them as parameters.
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest

from schemas.agent_schema import AgentOutput, AgentStatus, QueryCategory, Source
from schemas.email_schema import CleanEmail, EmailChunk
from schemas.memory_schema import VectorSearchResult


# ── Mock Memory Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_vector_store() -> MagicMock:
    """Provides a mock VectorStore with a default empty search result.

    Returns:
        A MagicMock configured to behave like VectorStore.
    """
    mock = MagicMock()
    mock.search.return_value = []
    mock.get_stats.return_value = {
        "collection_name": "test_collection",
        "total_documents": 0,
        "persist_directory": "./test_chroma",
        "embedding_model": "all-MiniLM-L6-v2",
    }
    return mock


@pytest.fixture
def mock_graph_store() -> MagicMock:
    """Provides a mock GraphStore with default empty query results.

    Returns:
        A MagicMock configured to behave like GraphStore.
    """
    mock = MagicMock()
    mock.get_person_by_email.return_value = None
    mock.get_decisions_by_person.return_value = []
    mock.get_communication_network.return_value = []
    mock.search_decisions.return_value = []
    mock.get_stats.return_value = {"Person": 0, "Decision": 0, "total_relationships": 0}
    return mock


@pytest.fixture
def mock_memory_manager(mock_vector_store: MagicMock, mock_graph_store: MagicMock) -> MagicMock:
    """Provides a mock MemoryManager wired to mock vector and graph stores.

    Args:
        mock_vector_store: The mocked VectorStore fixture.
        mock_graph_store: The mocked GraphStore fixture.

    Returns:
        A MagicMock configured to behave like MemoryManager, with
        _graph_store accessible for direct-session-style test patching.
    """
    mock = MagicMock()
    mock._vector_store = mock_vector_store
    mock._graph_store = mock_graph_store
    mock.search.return_value = []
    mock.search_by_sender.return_value = []
    mock.search_by_department.return_value = []
    mock.get_person.return_value = None
    mock.get_decisions_by_person.return_value = []
    mock.get_decisions_by_department.return_value = []
    mock.get_communication_network.return_value = []
    mock.search_decisions_graph.return_value = []
    mock.health_check.return_value = {
        "status": "healthy",
        "subsystems": {
            "vector_store": {"status": "healthy", "total_documents": 0},
            "graph_store": {"status": "healthy"},
            "cache": {"status": "healthy"},
        },
    }
    return mock


# ── Sample Domain Object Fixtures ─────────────────────────────────────────────

@pytest.fixture
def sample_clean_email() -> CleanEmail:
    """Provides a single valid CleanEmail instance for testing.

    Returns:
        A populated CleanEmail object.
    """
    return CleanEmail(
        message_id="<test123@enron.com>",
        date=datetime(2001, 5, 14, 16, 39, 0),
        sender="phillip.allen@enron.com",
        receiver="tim.belden@enron.com",
        subject="Q3 Budget Review",
        body=(
            "We decided to cut marketing spend by 15% due to the revenue "
            "shortfall this quarter. Tim approved the change after review."
        ),
        word_count=24,
        department="Sent Mail",
    )


@pytest.fixture
def sample_email_chunk() -> EmailChunk:
    """Provides a single valid EmailChunk instance for testing.

    Returns:
        A populated EmailChunk object.
    """
    return EmailChunk(
        chunk_id="test123_chunk_0",
        message_id="<test123@enron.com>",
        chunk_index=0,
        text="We decided to cut marketing spend by 15% due to the revenue shortfall.",
        sender="phillip.allen@enron.com",
        receiver="tim.belden@enron.com",
        subject="Q3 Budget Review",
        date="2001-05-14T16:39:00",
        word_count=13,
        department="Sent Mail",
    )


@pytest.fixture
def sample_vector_search_result() -> VectorSearchResult:
    """Provides a single VectorSearchResult instance for testing.

    Returns:
        A populated VectorSearchResult object with a fixed distance.
    """
    return VectorSearchResult(
        chunk_id="<test123@enron.com>",
        text="We decided to cut marketing spend by 15% due to the revenue shortfall.",
        distance=0.18,
        metadata={
            "message_id": "<test123@enron.com>",
            "sender": "phillip.allen@enron.com",
            "receiver": "tim.belden@enron.com",
            "subject": "Q3 Budget Review",
            "date": "2001-05-14T16:39:00",
            "department": "Sent Mail",
        },
    )


@pytest.fixture
def sample_source() -> Source:
    """Provides a single Source instance for testing.

    Returns:
        A populated Source object.
    """
    return Source(
        document_id="<test123@enron.com>",
        message_id="<test123@enron.com>",
        sender="phillip.allen@enron.com",
        date="2001-05-14T16:39:00",
        subject="Q3 Budget Review",
        excerpt="We decided to cut marketing spend by 15% due to the revenue shortfall.",
        relevance_score=0.82,
    )


@pytest.fixture
def sample_agent_output(sample_source: Source) -> AgentOutput:
    """Provides a single valid AgentOutput instance for testing.

    Args:
        sample_source: The sample Source fixture to attach.

    Returns:
        A populated AgentOutput object.
    """
    return AgentOutput(
        agent_name="DecisionAgent",
        query="Why did we cut marketing spend?",
        answer=(
            "Marketing spend was cut by 15% due to a revenue shortfall in Q3, "
            "as approved by Tim Belden. [Source 1]"
        ),
        sources=[sample_source],
        category=QueryCategory.DECISION,
        status=AgentStatus.SUCCESS,
        confidence=0.82,
        follow_up_questions=[
            "Who else was involved in this budget decision?",
            "What other cost-cutting measures were considered?",
        ],
    )


@pytest.fixture
def mock_llm_response() -> Mock:
    """Provides a mock LLM response object mimicking LangChain's message format.

    Returns:
        A Mock object with a .content attribute containing sample text.
    """
    mock = Mock()
    mock.content = (
        "Marketing spend was cut by 15% due to a revenue shortfall in Q3. "
        "[Source 1]\n\n"
        "FOLLOW_UP_1: Who else was involved in this decision?\n"
        "FOLLOW_UP_2: What other cost-cutting measures were considered?\n"
        "FOLLOW_UP_3: When was this policy reviewed next?"
    )
    return mock