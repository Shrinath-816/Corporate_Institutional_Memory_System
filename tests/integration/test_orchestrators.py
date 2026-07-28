"""
Module: tests/integration/test_orchestrators.py

Purpose:
    Integration tests focused on orchestrator-level coordination logic —
    verifying that each orchestrator correctly routes, aggregates, and
    falls back across its constituent agents, independent of the
    underlying data layer.

Responsibilities:
    - Test CaptureOrchestrator routes each ContentType to the correct
      capture agent, and validates required fields per type.
    - Test AuditOrchestrator aggregates findings from all three audit
      agents, respects scope filtering, and computes overall health.
    - Test RetrievalOrchestrator's fallback and multi-agent behaviour
      when router confidence is low or category is UNKNOWN.
    - Test MasterOrchestrator dispatches each RequestType to the
      correct sub-orchestrator.

Notes:
    Sub-orchestrator internals (agent instances) are patched directly
    on already-constructed orchestrator objects, keeping these tests
    focused purely on coordination/routing logic rather than agent
    internals or real data storage (covered in test_full_pipeline.py).
"""

from unittest.mock import MagicMock, patch

import pytest

from agents.capture.tribal_knowledge_agent import (
    ExpertProfile,
    TribalKnowledgeReport,
)
from agents.capture.meeting_agent import MeetingExtractionOutput
from agents.capture.postmortem_agent import PostMortemExtractionOutput
from agents.audit.gap_detector_agent import GapDetectorOutput
from agents.audit.staleness_agent import StalenessScanOutput
from agents.audit.single_point_failure_agent import SPFScanOutput
from orchestrators.capture_orchestrator import (
    CaptureOrchestrator,
    CaptureRequest,
    ContentType,
)
from orchestrators.audit_orchestrator import (
    AuditOrchestrator,
    AuditRequest,
    AuditScope,
)
from orchestrators.retrieval_orchestrator import (
    RetrievalOrchestrator,
    RetrievalRequest,
)
from orchestrators.master_orchestrator import (
    MasterOrchestrator,
    MasterRequest,
    RequestType,
)
from schemas.agent_schema import AgentOutput, AgentStatus, QueryCategory
from schemas.memory_schema import KnowledgeGap, KnowledgeGapSeverity


# ── Shared Fixture: patch LLM client construction ────────────────────────────

@pytest.fixture(autouse=True)
def patch_llm_client():
    """Patches ChatGoogleGenerativeAI construction for every test in this module."""
    with patch("agents.base_agent.ChatGoogleGenerativeAI") as mock_llm_class:
        mock_llm_class.return_value = MagicMock()
        yield mock_llm_class


# ── CaptureOrchestrator: routing ─────────────────────────────────────────────

class TestCaptureOrchestratorRouting:
    """Tests for CaptureOrchestrator's content-type routing logic."""

    def test_routes_meeting_transcript_to_meeting_agent(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """MEETING_TRANSCRIPT content type should invoke MeetingAgent only."""
        orchestrator = CaptureOrchestrator(memory=mock_memory_manager)
        orchestrator._meeting_agent.extract_from_content = MagicMock(
            return_value=MeetingExtractionOutput(
                meeting_id="m1",
                summary="Team decided to delay launch.",
                decisions=[],
                action_items=[],
                stored_in_graph=True,
                stored_in_vector=True,
            )
        )
        orchestrator._postmortem_agent.extract_from_content = MagicMock()
        orchestrator._tribal_agent.conduct_interview = MagicMock()

        request = CaptureRequest(
            content="We discussed the launch timeline and decided to delay it.",
            content_type=ContentType.MEETING_TRANSCRIPT,
        )
        result = orchestrator.capture(request)

        orchestrator._meeting_agent.extract_from_content.assert_called_once()
        orchestrator._postmortem_agent.extract_from_content.assert_not_called()
        orchestrator._tribal_agent.conduct_interview.assert_not_called()
        assert result.success is True
        assert result.agent_used == "MeetingAgent"

    def test_routes_post_mortem_to_postmortem_agent(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """POST_MORTEM content type should invoke PostMortemAgent only."""
        orchestrator = CaptureOrchestrator(memory=mock_memory_manager)
        orchestrator._postmortem_agent.extract_from_content = MagicMock(
            return_value=PostMortemExtractionOutput(
                postmortem_id="p1",
                project_name="Sagewood",
                summary="Migration completed with delays.",
                stored_in_graph=True,
                stored_in_vector=True,
            )
        )
        orchestrator._meeting_agent.extract_from_content = MagicMock()

        request = CaptureRequest(
            content="Project retrospective: the Sagewood migration had delays "
                    "due to vendor onboarding issues.",
            content_type=ContentType.POST_MORTEM,
        )
        result = orchestrator.capture(request)

        orchestrator._postmortem_agent.extract_from_content.assert_called_once()
        orchestrator._meeting_agent.extract_from_content.assert_not_called()
        assert result.agent_used == "PostMortemAgent"

    def test_tribal_knowledge_requires_expert_profile(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """TRIBAL_KNOWLEDGE without expert_profile should fail gracefully, not raise."""
        orchestrator = CaptureOrchestrator(memory=mock_memory_manager)

        request = CaptureRequest(
            content="Some interview responses about undocumented processes here.",
            content_type=ContentType.TRIBAL_KNOWLEDGE,
            expert_profile=None,
        )
        result = orchestrator.capture(request)

        assert result.success is False
        assert "expert_profile" in result.error

    def test_tribal_knowledge_with_profile_routes_correctly(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """TRIBAL_KNOWLEDGE with a valid expert_profile should invoke TribalKnowledgeAgent."""
        orchestrator = CaptureOrchestrator(memory=mock_memory_manager)
        orchestrator._tribal_agent.conduct_interview = MagicMock(
            return_value=TribalKnowledgeReport(
                interview_id="t1",
                expert_email="jane@enron.com",
                expert_name="Jane Doe",
                domain="finance",
                summary="Captured undocumented approval process knowledge.",
                stored_in_graph=True,
                stored_in_vector=True,
            )
        )

        profile = ExpertProfile(
            name="Jane Doe", email="jane@enron.com", domain="finance"
        )
        request = CaptureRequest(
            content="Only I know the informal vendor payment approval process.",
            content_type=ContentType.TRIBAL_KNOWLEDGE,
            expert_profile=profile,
        )
        result = orchestrator.capture(request)

        orchestrator._tribal_agent.conduct_interview.assert_called_once()
        assert result.success is True
        assert result.agent_used == "TribalKnowledgeAgent"

    def test_agent_exception_is_caught_and_returns_failed_result(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """An exception inside a capture agent should not propagate to the caller."""
        orchestrator = CaptureOrchestrator(memory=mock_memory_manager)
        orchestrator._meeting_agent.extract_from_content = MagicMock(
            side_effect=RuntimeError("extraction failed")
        )

        request = CaptureRequest(
            content="Some meeting content goes here for testing purposes.",
            content_type=ContentType.MEETING_TRANSCRIPT,
        )
        result = orchestrator.capture(request)

        assert result.success is False
        assert "extraction failed" in result.error


# ── AuditOrchestrator: aggregation & scope ────────────────────────────────────

class TestAuditOrchestratorAggregation:
    """Tests for AuditOrchestrator's finding aggregation and scope handling."""

    def _make_gap_output(self) -> GapDetectorOutput:
        return GapDetectorOutput(
            total_documents=100,
            gaps_found=1,
            critical_gaps=1,
            gaps=[
                KnowledgeGap(
                    gap_id="gap1",
                    description="Legal department has no documentation.",
                    affected_area="Legal",
                    severity=KnowledgeGapSeverity.CRITICAL,
                    recommended_action="Ingest legal department emails.",
                )
            ],
            summary="One critical gap found.",
        )

    def _make_staleness_output(self) -> StalenessScanOutput:
        from agents.audit.staleness_agent import StalenessReport

        return StalenessScanOutput(
            total_documents=100,
            total_findings=1,
            critical_findings=0,
            findings=[
                StalenessReport(
                    report_id="stale1",
                    affected_area="Finance",
                    last_activity="2001-01-01T00:00:00",
                    age_days=400,
                    severity="MEDIUM",
                    description="Finance content is over a year old.",
                    recommended_action="Refresh finance documentation.",
                )
            ],
            summary="One staleness finding.",
        )

    def _make_spf_output(self) -> SPFScanOutput:
        from agents.audit.single_point_failure_agent import SinglePointOfFailure

        return SPFScanOutput(
            total_documents=100,
            total_contributors=10,
            spf_count=1,
            critical_spf_count=1,
            findings=[
                SinglePointOfFailure(
                    spf_id="spf1",
                    person_email="key.person@enron.com",
                    document_count=40,
                    contribution_percent=40.0,
                    risk_level="CRITICAL",
                    description="This person holds 40% of institutional memory.",
                    recommended_action="Begin knowledge transfer immediately.",
                )
            ],
            summary="One critical SPF risk found.",
        )

    def test_full_scope_runs_all_three_agents(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """AuditScope.FULL should invoke gap, staleness, and SPF agents."""
        orchestrator = AuditOrchestrator(memory=mock_memory_manager)
        orchestrator._gap_agent.scan = MagicMock(return_value=self._make_gap_output())
        orchestrator._staleness_agent.scan = MagicMock(return_value=self._make_staleness_output())
        orchestrator._spf_agent.scan = MagicMock(return_value=self._make_spf_output())
        orchestrator._generate_executive_summary = MagicMock(return_value="Summary text.")

        report = orchestrator.audit(AuditRequest(scope=AuditScope.FULL))

        orchestrator._gap_agent.scan.assert_called_once()
        orchestrator._staleness_agent.scan.assert_called_once()
        orchestrator._spf_agent.scan.assert_called_once()
        assert report.total_findings == 3

    def test_gaps_only_scope_skips_other_agents(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """AuditScope.GAPS_ONLY should only invoke the gap detector agent."""
        orchestrator = AuditOrchestrator(memory=mock_memory_manager)
        orchestrator._gap_agent.scan = MagicMock(return_value=self._make_gap_output())
        orchestrator._staleness_agent.scan = MagicMock()
        orchestrator._spf_agent.scan = MagicMock()
        orchestrator._generate_executive_summary = MagicMock(return_value="Summary.")

        orchestrator.audit(AuditRequest(scope=AuditScope.GAPS_ONLY))

        orchestrator._gap_agent.scan.assert_called_once()
        orchestrator._staleness_agent.scan.assert_not_called()
        orchestrator._spf_agent.scan.assert_not_called()

    def test_findings_sorted_by_severity_critical_first(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """Aggregated findings should be sorted with CRITICAL severity first."""
        orchestrator = AuditOrchestrator(memory=mock_memory_manager)
        orchestrator._gap_agent.scan = MagicMock(return_value=self._make_gap_output())
        orchestrator._staleness_agent.scan = MagicMock(return_value=self._make_staleness_output())
        orchestrator._spf_agent.scan = MagicMock(return_value=self._make_spf_output())
        orchestrator._generate_executive_summary = MagicMock(return_value="Summary.")

        report = orchestrator.audit(AuditRequest(scope=AuditScope.FULL))

        severities = [f.severity for f in report.findings]
        assert severities[0] == "CRITICAL"

    def test_overall_health_critical_when_enough_critical_findings(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """3+ critical findings should push overall_health to CRITICAL."""
        orchestrator = AuditOrchestrator(memory=mock_memory_manager)

        # Force 3 critical findings across two agent outputs
        gap_output = self._make_gap_output()
        gap_output.gaps.append(
            KnowledgeGap(
                gap_id="gap2", description="Another gap", affected_area="HR",
                severity=KnowledgeGapSeverity.CRITICAL,
                recommended_action="Ingest HR data.",
            )
        )
        orchestrator._gap_agent.scan = MagicMock(return_value=gap_output)
        orchestrator._staleness_agent.scan = MagicMock(return_value=self._make_staleness_output())
        orchestrator._spf_agent.scan = MagicMock(return_value=self._make_spf_output())
        orchestrator._generate_executive_summary = MagicMock(return_value="Summary.")

        report = orchestrator.audit(AuditRequest(scope=AuditScope.FULL))

        assert report.critical_findings == 3
        assert report.overall_health == "CRITICAL"

    def test_no_findings_produces_healthy_status_without_llm_call(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """Zero findings should short-circuit to a default healthy summary."""
        orchestrator = AuditOrchestrator(memory=mock_memory_manager)
        orchestrator._gap_agent.scan = MagicMock(
            return_value=GapDetectorOutput(
                total_documents=100, gaps_found=0, critical_gaps=0,
                gaps=[], summary="No gaps.",
            )
        )
        orchestrator._staleness_agent.scan = MagicMock(
            return_value=StalenessScanOutput(
                total_documents=100, total_findings=0, critical_findings=0,
                findings=[], summary="No staleness.",
            )
        )
        orchestrator._spf_agent.scan = MagicMock(
            return_value=SPFScanOutput(
                total_documents=100, total_contributors=10, spf_count=0,
                critical_spf_count=0, findings=[], summary="No SPF risk.",
            )
        )
        orchestrator._generate_executive_summary = MagicMock()

        report = orchestrator.audit(AuditRequest(scope=AuditScope.FULL))

        assert report.overall_health == "HEALTHY"
        orchestrator._generate_executive_summary.assert_not_called()

    def test_one_agent_failure_does_not_abort_the_scan(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """If one audit agent raises, the other agents' findings should still be aggregated."""
        orchestrator = AuditOrchestrator(memory=mock_memory_manager)
        orchestrator._gap_agent.scan = MagicMock(side_effect=RuntimeError("gap agent crashed"))
        orchestrator._staleness_agent.scan = MagicMock(return_value=self._make_staleness_output())
        orchestrator._spf_agent.scan = MagicMock(return_value=self._make_spf_output())
        orchestrator._generate_executive_summary = MagicMock(return_value="Summary.")

        report = orchestrator.audit(AuditRequest(scope=AuditScope.FULL))

        # Staleness + SPF findings should still be present despite gap agent failure
        assert report.total_findings == 2


# ── RetrievalOrchestrator: fallback & multi-agent ─────────────────────────────

class TestRetrievalOrchestratorFallback:
    """Tests for RetrievalOrchestrator's fallback and multi-agent dispatch logic."""

    def test_low_confidence_triggers_fallback_agent(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """Low primary confidence with a valid fallback category should trigger fallback."""
        orchestrator = RetrievalOrchestrator(memory=mock_memory_manager)

        low_confidence_output = AgentOutput(
            agent_name="DecisionAgent", query="q", answer="unsure",
            sources=[], category=QueryCategory.DECISION,
            status=AgentStatus.PARTIAL, confidence=0.1,
        )
        high_confidence_fallback = AgentOutput(
            agent_name="PolicyAgent", query="q", answer="better answer",
            sources=[], category=QueryCategory.POLICY,
            status=AgentStatus.SUCCESS, confidence=0.85,
        )

        orchestrator._router.classify = MagicMock(
            return_value=type(
                "R", (), {
                    "category": QueryCategory.DECISION,
                    "confidence": 0.4,
                    "fallback_category": QueryCategory.POLICY,
                    "reasoning": "ambiguous",
                    "query": "q",
                }
            )()
        )
        orchestrator._decision_agent.execute = MagicMock(return_value=low_confidence_output)
        orchestrator._policy_agent.execute = MagicMock(return_value=high_confidence_fallback)

        result = orchestrator.retrieve(RetrievalRequest(query="ambiguous question"))

        orchestrator._policy_agent.execute.assert_called_once()
        assert result.agent_name == "PolicyAgent"
        assert result.confidence == 0.85

    def test_high_confidence_primary_does_not_trigger_fallback(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A confident primary result should not invoke the fallback agent."""
        orchestrator = RetrievalOrchestrator(memory=mock_memory_manager)

        confident_output = AgentOutput(
            agent_name="DecisionAgent", query="q", answer="confident answer",
            sources=[], category=QueryCategory.DECISION,
            status=AgentStatus.SUCCESS, confidence=0.9,
        )

        orchestrator._router.classify = MagicMock(
            return_value=type(
                "R", (), {
                    "category": QueryCategory.DECISION,
                    "confidence": 0.95,
                    "fallback_category": QueryCategory.POLICY,
                    "reasoning": "clear",
                    "query": "q",
                }
            )()
        )
        orchestrator._decision_agent.execute = MagicMock(return_value=confident_output)
        orchestrator._policy_agent.execute = MagicMock()

        result = orchestrator.retrieve(RetrievalRequest(query="clear question"))

        orchestrator._policy_agent.execute.assert_not_called()
        assert result.agent_name == "DecisionAgent"

    def test_category_hint_bypasses_router_classification(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A provided category_hint should skip router.classify entirely."""
        orchestrator = RetrievalOrchestrator(memory=mock_memory_manager)
        orchestrator._router.classify = MagicMock()
        orchestrator._project_agent.execute = MagicMock(
            return_value=AgentOutput(
                agent_name="ProjectAgent", query="q", answer="a",
                sources=[], category=QueryCategory.PROJECT,
                status=AgentStatus.SUCCESS, confidence=0.7,
            )
        )

        orchestrator.retrieve(
            RetrievalRequest(query="q", category_hint=QueryCategory.PROJECT)
        )

        orchestrator._router.classify.assert_not_called()
        orchestrator._project_agent.execute.assert_called_once()

    def test_competitive_signal_overrides_category_routing(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """Competitive language in the query should route to CompetitiveAgent."""
        orchestrator = RetrievalOrchestrator(memory=mock_memory_manager)
        orchestrator._router.classify = MagicMock(
            return_value=type(
                "R", (), {
                    "category": QueryCategory.DECISION,
                    "confidence": 0.8,
                    "fallback_category": None,
                    "reasoning": "test",
                    "query": "q",
                }
            )()
        )
        orchestrator._competitive_agent.execute = MagicMock(
            return_value=AgentOutput(
                agent_name="CompetitiveAgent", query="q", answer="a",
                sources=[], category=QueryCategory.DECISION,
                status=AgentStatus.SUCCESS, confidence=0.7,
            )
        )
        orchestrator._decision_agent.execute = MagicMock()

        orchestrator.retrieve(
            RetrievalRequest(query="How does our pricing compare to our competitor?")
        )

        orchestrator._competitive_agent.execute.assert_called_once()
        orchestrator._decision_agent.execute.assert_not_called()


# ── MasterOrchestrator: request type dispatch ────────────────────────────────

class TestMasterOrchestratorDispatch:
    """Tests for MasterOrchestrator routing each RequestType correctly."""

    def test_query_request_routes_to_retrieval_orchestrator(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A QUERY request should delegate to the RetrievalOrchestrator only."""
        master = MasterOrchestrator(memory=mock_memory_manager)
        master._retrieval.retrieve = MagicMock(
            return_value=AgentOutput(
                agent_name="DecisionAgent", query="q", answer="a",
                sources=[], status=AgentStatus.SUCCESS, confidence=0.8,
            )
        )
        master._capture.capture = MagicMock()
        master._audit.audit = MagicMock()

        response = master.process(
            MasterRequest(request_type=RequestType.QUERY, query="test query")
        )

        master._retrieval.retrieve.assert_called_once()
        master._capture.capture.assert_not_called()
        master._audit.audit.assert_not_called()
        assert response.success is True
        assert response.query_result is not None

    def test_capture_request_routes_to_capture_orchestrator(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A CAPTURE request should delegate to the CaptureOrchestrator only."""
        from orchestrators.capture_orchestrator import CaptureResult

        master = MasterOrchestrator(memory=mock_memory_manager)
        master._capture.capture = MagicMock(
            return_value=CaptureResult(
                content_type=ContentType.MEETING_TRANSCRIPT,
                agent_used="MeetingAgent", success=True,
                summary="Captured.", items_captured=2,
                stored_in_graph=True, stored_in_vector=True,
            )
        )
        master._retrieval.retrieve = MagicMock()

        response = master.process(
            MasterRequest(
                request_type=RequestType.CAPTURE,
                capture_request=CaptureRequest(
                    content="Meeting content for testing purposes here.",
                    content_type=ContentType.MEETING_TRANSCRIPT,
                ),
            )
        )

        master._capture.capture.assert_called_once()
        master._retrieval.retrieve.assert_not_called()
        assert response.capture_result is not None
        assert response.capture_result.success is True

    def test_capture_request_without_payload_returns_error(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A CAPTURE request missing capture_request should fail gracefully."""
        master = MasterOrchestrator(memory=mock_memory_manager)

        response = master.process(
            MasterRequest(request_type=RequestType.CAPTURE, capture_request=None)
        )

        assert response.success is False
        assert "capture_request is required" in response.error

    def test_audit_request_routes_to_audit_orchestrator(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """An AUDIT request should delegate to the AuditOrchestrator only."""
        from orchestrators.audit_orchestrator import AuditReport

        master = MasterOrchestrator(memory=mock_memory_manager)
        master._audit.audit = MagicMock(
            return_value=AuditReport(
                report_id="r1", scope=AuditScope.FULL,
                total_findings=0, critical_findings=0, high_findings=0,
                findings=[], overall_health="HEALTHY",
                executive_summary="All clear.",
            )
        )
        master._retrieval.retrieve = MagicMock()

        response = master.process(
            MasterRequest(request_type=RequestType.AUDIT, audit_scope=AuditScope.FULL)
        )

        master._audit.audit.assert_called_once()
        master._retrieval.retrieve.assert_not_called()
        assert response.audit_report is not None
        assert response.audit_report.overall_health == "HEALTHY"

    def test_health_request_does_not_touch_sub_orchestrators(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """A HEALTH request should only query the memory manager, not sub-orchestrators."""
        master = MasterOrchestrator(memory=mock_memory_manager)
        master._retrieval.retrieve = MagicMock()
        master._capture.capture = MagicMock()
        master._audit.audit = MagicMock()

        response = master.process(MasterRequest(request_type=RequestType.HEALTH))

        master._retrieval.retrieve.assert_not_called()
        master._capture.capture.assert_not_called()
        master._audit.audit.assert_not_called()
        assert response.health_status is not None

    def test_query_convenience_method_raises_on_orchestrator_failure(
        self, mock_memory_manager: MagicMock
    ) -> None:
        """The query() convenience method should raise RuntimeError on failure."""
        master = MasterOrchestrator(memory=mock_memory_manager)
        master._retrieval.retrieve = MagicMock(
            side_effect=RuntimeError("retrieval crashed")
        )

        with pytest.raises(RuntimeError):
            master.query("this will fail")