"""
Module: tests/unit/test_agents.py

Purpose:
    Unit tests for the agent layer — BaseAgent shared utilities,
    RouterAgent query classification, and DecisionAgent's retrieval
    and synthesis pipeline.

Responsibilities:
    - Test BaseAgent's context building, source extraction, and output
      construction using a minimal concrete test subclass.
    - Test RouterAgent's structured LLM response parsing under valid,
      malformed, and edge-case inputs.
    - Test DecisionAgent's full run() flow with mocked memory and LLM.

Notes:
    ChatGoogleGenerativeAI is patched at construction time across all
    tests in this module so no real API client or network call is made.
"""

from unittest.mock import MagicMock, patch

import pytest

from agents.base_agent import BaseAgent
from agents.retrieval.router_agent import RouterAgent, RouterOutput
from agents.retrieval.decision_agent import DecisionAgent
from schemas.agent_schema import (
    AgentInput,
    AgentOutput,
    AgentStatus,
    QueryCategory,
    Source,
)
from schemas.memory_schema import VectorSearchResult


# ── Shared Fixture: patch the LLM client construction ────────────────────────

@pytest.fixture(autouse=True)
def patch_llm_client():
    """Patches ChatGoogleGenerativeAI construction for every test in this module.

    Prevents real API client instantiation (and any accidental network
    calls) while still allowing tests to control _invoke_llm behaviour
    directly on agent instances.
    """
    with patch("agents.base_agent.ChatGoogleGenerativeAI") as mock_llm_class:
        mock_llm_class.return_value = MagicMock()
        yield mock_llm_class


# ── Minimal Concrete Agent for BaseAgent Testing ──────────────────────────────

class _DummyAgent(BaseAgent):
    """Minimal concrete BaseAgent subclass used to test shared utilities."""

    def __init__(self, memory=None):
        super().__init__(
            agent_name="DummyAgent", category=QueryCategory.UNKNOWN, memory=memory
        )

    def _build_prompt(self, query: str, context: str) -> str:
        return f"QUERY: {query}\nCONTEXT: {context}"

    def run(self, agent_input: AgentInput) -> AgentOutput:
        return self._build_output(
            query=agent_input.query,
            answer="dummy answer",
            sources=[],
        )


# ── BaseAgent: context building ───────────────────────────────────────────────

class TestBaseAgentContextBuilding:
    """Tests for BaseAgent._build_context()."""

    def test_empty_results_returns_fallback_message(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """An empty results list should produce a 'no documents' fallback string."""
        agent = _DummyAgent(memory=mock_memory_manager)
        context = agent._build_context([])
        assert "No relevant documents" in context

    def test_context_includes_all_result_fields(
        self,
        mock_memory_manager: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """Built context should include sender, date, subject, and text."""
        agent = _DummyAgent(memory=mock_memory_manager)
        context = agent._build_context([sample_vector_search_result])

        assert sample_vector_search_result.metadata["sender"] in context
        assert sample_vector_search_result.metadata["subject"] in context
        assert sample_vector_search_result.text in context

    def test_context_numbers_multiple_sources(
        self,
        mock_memory_manager: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """Multiple results should be numbered [Source 1], [Source 2], etc."""
        agent = _DummyAgent(memory=mock_memory_manager)
        second = sample_vector_search_result.model_copy(
            update={"chunk_id": "second_chunk"}
        )
        context = agent._build_context([sample_vector_search_result, second])

        assert "[Source 1]" in context
        assert "[Source 2]" in context


# ── BaseAgent: source extraction ──────────────────────────────────────────────

class TestBaseAgentSourceExtraction:
    """Tests for BaseAgent._extract_sources()."""

    def test_extracts_source_with_correct_fields(
        self,
        mock_memory_manager: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """Extracted Source objects should carry over metadata correctly."""
        agent = _DummyAgent(memory=mock_memory_manager)
        sources = agent._extract_sources([sample_vector_search_result])

        assert len(sources) == 1
        assert sources[0].sender == sample_vector_search_result.metadata["sender"]
        assert sources[0].relevance_score == sample_vector_search_result.relevance_score

    def test_excerpt_truncated_to_300_chars(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """Excerpts longer than 300 characters should be truncated."""
        long_result = VectorSearchResult(
            chunk_id="long_chunk",
            text="x" * 500,
            distance=0.1,
            metadata={"message_id": "m1", "sender": "a@b.com"},
        )
        agent = _DummyAgent(memory=mock_memory_manager)
        sources = agent._extract_sources([long_result])

        assert len(sources[0].excerpt) == 300


# ── BaseAgent: output building & empty result handling ────────────────────────

class TestBaseAgentOutputBuilding:
    """Tests for BaseAgent._build_output() and _handle_empty_results()."""

    def test_build_output_sets_all_fields(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """_build_output should populate agent_name, category, and status correctly."""
        agent = _DummyAgent(memory=mock_memory_manager)
        output = agent._build_output(
            query="test query",
            answer="test answer",
            sources=[],
            confidence=0.9,
        )

        assert output.agent_name == "DummyAgent"
        assert output.category == QueryCategory.UNKNOWN
        assert output.status == AgentStatus.SUCCESS
        assert output.confidence == 0.9

    def test_handle_empty_results_returns_partial_status(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """_handle_empty_results should return PARTIAL status with zero confidence."""
        agent = _DummyAgent(memory=mock_memory_manager)
        output = agent._handle_empty_results("unanswerable query")

        assert output.status == AgentStatus.PARTIAL
        assert output.confidence == 0.0
        assert output.sources == []


# ── BaseAgent: execute() wrapper ──────────────────────────────────────────────

class TestBaseAgentExecute:
    """Tests for BaseAgent.execute() — the orchestrator-facing entry point."""

    def test_execute_returns_run_output_on_success(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """execute() should return exactly what run() produces on success."""
        agent = _DummyAgent(memory=mock_memory_manager)
        agent_input = AgentInput(query="hello world")

        output = agent.execute(agent_input)

        assert output.answer == "dummy answer"
        assert output.status == AgentStatus.SUCCESS

    def test_execute_catches_exceptions_and_returns_failed_status(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """If run() raises, execute() should catch it and return FAILED status."""

        class _BrokenAgent(BaseAgent):
            def __init__(self, memory=None):
                super().__init__("BrokenAgent", QueryCategory.UNKNOWN, memory=memory)

            def _build_prompt(self, query, context):
                return ""

            def run(self, agent_input):
                raise RuntimeError("simulated failure")

        agent = _BrokenAgent(memory=mock_memory_manager)
        output = agent.execute(AgentInput(query="trigger failure"))

        assert output.status == AgentStatus.FAILED
        assert "simulated failure" in output.answer


# ── RouterAgent: prompt building ──────────────────────────────────────────────

class TestRouterAgentPrompt:
    """Tests for RouterAgent._build_prompt()."""

    def test_prompt_includes_query_and_categories(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """The classification prompt must include the query and all categories."""
        agent = RouterAgent(memory=mock_memory_manager)
        prompt = agent._build_prompt("Why did we cancel the trip?")

        assert "Why did we cancel the trip?" in prompt
        assert "DECISION" in prompt
        assert "PEOPLE" in prompt
        assert "POLICY" in prompt
        assert "PROJECT" in prompt


# ── RouterAgent: response parsing ─────────────────────────────────────────────

class TestRouterAgentParsing:
    """Tests for RouterAgent._parse_llm_response()."""

    def test_parses_valid_structured_response(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A well-formatted LLM response should parse into correct fields."""
        agent = RouterAgent(memory=mock_memory_manager)
        response = (
            "CATEGORY: DECISION\n"
            "CONFIDENCE: 0.92\n"
            "REASONING: The query asks why a decision was made.\n"
            "FALLBACK: NONE"
        )

        result = agent._parse_llm_response(response, "why did we do X?")

        assert result.category == QueryCategory.DECISION
        assert result.confidence == 0.92
        assert result.fallback_category is None

    def test_unknown_category_defaults_to_unknown_enum(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """An unrecognised category string should default to UNKNOWN."""
        agent = RouterAgent(memory=mock_memory_manager)
        response = (
            "CATEGORY: BANANA\n"
            "CONFIDENCE: 0.5\n"
            "REASONING: test\n"
            "FALLBACK: NONE"
        )

        result = agent._parse_llm_response(response, "test query")
        assert result.category == QueryCategory.UNKNOWN

    def test_confidence_out_of_bounds_is_clamped(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A confidence value above 1.0 should be clamped to 1.0."""
        agent = RouterAgent(memory=mock_memory_manager)
        response = (
            "CATEGORY: PEOPLE\n"
            "CONFIDENCE: 1.5\n"
            "REASONING: test\n"
            "FALLBACK: NONE"
        )

        result = agent._parse_llm_response(response, "test query")
        assert result.confidence == 1.0

    def test_valid_fallback_category_is_parsed(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A valid fallback category should be parsed into the enum."""
        agent = RouterAgent(memory=mock_memory_manager)
        response = (
            "CATEGORY: PROJECT\n"
            "CONFIDENCE: 0.6\n"
            "REASONING: ambiguous\n"
            "FALLBACK: DECISION"
        )

        result = agent._parse_llm_response(response, "test query")
        assert result.fallback_category == QueryCategory.DECISION

    def test_malformed_response_falls_back_gracefully(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A response with no recognisable fields should not raise."""
        agent = RouterAgent(memory=mock_memory_manager)
        result = agent._parse_llm_response("garbage unstructured text", "test")

        assert result.category == QueryCategory.UNKNOWN
        assert 0.0 <= result.confidence <= 1.0


# ── RouterAgent: classify() end-to-end ────────────────────────────────────────

class TestRouterAgentClassify:
    """Tests for RouterAgent.classify() with a mocked LLM invocation."""

    def test_classify_returns_router_output(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """classify() should invoke the LLM and return a valid RouterOutput."""
        agent = RouterAgent(memory=mock_memory_manager)
        agent._invoke_llm = MagicMock(
            return_value=(
                "CATEGORY: POLICY\n"
                "CONFIDENCE: 0.88\n"
                "REASONING: asks about a rule\n"
                "FALLBACK: NONE"
            )
        )

        result = agent.classify("What is our travel policy?")

        assert isinstance(result, RouterOutput)
        assert result.category == QueryCategory.POLICY
        assert result.confidence == 0.88

    def test_classify_handles_llm_failure_gracefully(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """If the LLM call raises, classify() should return a safe UNKNOWN result."""
        agent = RouterAgent(memory=mock_memory_manager)
        agent._invoke_llm = MagicMock(side_effect=RuntimeError("LLM down"))

        result = agent.classify("any query")

        assert result.category == QueryCategory.UNKNOWN
        assert result.confidence == 0.0


# ── DecisionAgent: run() pipeline ─────────────────────────────────────────────

class TestDecisionAgentRun:
    """Tests for DecisionAgent.run() with mocked retrieval and LLM."""

    def test_returns_partial_status_when_no_results(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """No retrieved chunks should short-circuit to _handle_empty_results."""
        mock_memory_manager.search.return_value = []
        agent = DecisionAgent(memory=mock_memory_manager)

        output = agent.run(AgentInput(query="unanswerable question"))

        assert output.status == AgentStatus.PARTIAL
        assert output.confidence == 0.0

    def test_successful_run_returns_answer_and_sources(
        self,
        mock_memory_manager: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """A successful run with retrieved chunks should produce a full answer."""
        mock_memory_manager.search.return_value = [sample_vector_search_result]

        agent = DecisionAgent(memory=mock_memory_manager)
        agent._invoke_llm = MagicMock(
            return_value=(
                "Marketing spend was cut due to revenue shortfall. [Source 1]\n\n"
                "FOLLOW_UP_1: Who approved this?\n"
                "FOLLOW_UP_2: What was the total savings?\n"
                "FOLLOW_UP_3: When will this be reviewed?"
            )
        )

        output = agent.run(AgentInput(query="Why was marketing spend cut?"))

        assert output.status == AgentStatus.SUCCESS
        assert len(output.sources) == 1
        assert len(output.follow_up_questions) == 3
        assert "FOLLOW_UP" not in output.answer

    def test_llm_failure_returns_failed_status(
        self,
        mock_memory_manager: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """An LLM invocation failure should produce a FAILED AgentOutput, not raise."""
        mock_memory_manager.search.return_value = [sample_vector_search_result]

        agent = DecisionAgent(memory=mock_memory_manager)
        agent._invoke_llm = MagicMock(side_effect=RuntimeError("Gemini timeout"))

        output = agent.run(AgentInput(query="Why did this happen?"))

        assert output.status == AgentStatus.FAILED

    def test_confidence_penalised_on_insufficient_evidence_language(
        self,
        mock_memory_manager: MagicMock,
        sample_vector_search_result: VectorSearchResult,
    ) -> None:
        """Answers signalling insufficient evidence should have reduced confidence."""
        mock_memory_manager.search.return_value = [sample_vector_search_result]

        agent = DecisionAgent(memory=mock_memory_manager)
        agent._invoke_llm = MagicMock(
            return_value="I cannot find sufficient evidence for this decision."
        )

        output = agent.run(AgentInput(query="Why did X happen?"))

        # High relevance source (0.82) minus 0.2 penalty should still be < raw relevance
        assert output.confidence < sample_vector_search_result.relevance_score