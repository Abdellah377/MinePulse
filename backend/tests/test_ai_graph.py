from datetime import date, datetime, time, timezone
from dataclasses import fields
import sys

from app.ai.contracts import (
    ConfidenceLevel,
    Contradiction,
    DiagnosisResult,
    EvidenceItem,
    EvidenceKind,
    EvidenceRequest,
    EvidenceRequestType,
    EvidenceStatus,
    Hypothesis,
    InvestigationConclusion,
    InvestigationRecommendation,
    InvestigationStatus,
    InvestigationSubject,
    InvestigationTrigger,
    RecommendationAction,
    TriggerSource,
    TriggerType,
)
from app.ai.graph import build_investigation_graph, initial_state
from app.ai.nodes import InvestigationRuntime
from app.ai.routers import route_after_analysis
from app.db.models import Shift, Site
from app.services.operational.context import OperationalContext


def _ctx() -> OperationalContext:
    site = Site(site_id=1, code="SITE-A", name="Site A", active=True)
    shift = Shift(
        shift_id=2,
        site_id=1,
        name="Day",
        shift_date=date(2026, 8, 24),
        start_time=time(6),
        end_time=time(14),
    )
    return OperationalContext(
        site=site,
        shift=shift,
        sim_now=datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        shift_window_start=datetime(2026, 8, 24, 6, tzinfo=timezone.utc),
        shift_window_end=datetime(2026, 8, 24, 14, tzinfo=timezone.utc),
    )


def _trigger() -> InvestigationTrigger:
    return InvestigationTrigger(
        trigger_type=TriggerType.PRODUCTION_DEVIATION,
        trigger_source=TriggerSource.USER_INVESTIGATE,
        subject=InvestigationSubject.PRODUCTION,
        source="test",
        site_id=1,
        shift_id=2,
    )


def _evidence(evidence_id="ev-production", metric="shift_production_summary"):
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=EvidenceKind.DERIVED_METRIC,
        source_tool="shift_production",
        source_service="app.services.operational.production.production_summary",
        metric=metric,
        value={"tonnage": 80, "target": 100},
        site_id=1,
        shift_id=2,
        observed_at=_ctx().sim_now,
    )


class FakeTools:
    def __init__(self, *, requested_available=True):
        self.request_calls = 0
        self.requested_available = requested_available

    def gather_initial(self, ctx, trigger):
        return [_evidence()]

    def gather_requested(self, ctx, requests):
        self.request_calls += 1
        if not self.requested_available:
            return [
                EvidenceItem(
                    evidence_id=f"ev-unavailable-{self.request_calls}",
                    kind=EvidenceKind.FACT,
                    source_tool="downtime",
                    source_service="app.services.operational.downtime.downtime_reasons",
                    metric="downtime_by_reason",
                    value=None,
                    available=False,
                    status=EvidenceStatus.UNAVAILABLE,
                    site_id=ctx.site_id,
                    shift_id=ctx.shift_id,
                )
                for _ in requests
            ]
        return [_evidence(f"ev-extra-{self.request_calls}", "downtime_by_reason")]


class ScriptedProvider:
    provider_name = "mock"
    model_name = "mock-structured"

    def __init__(self, diagnoses):
        self.diagnoses = list(diagnoses)
        self.diagnose_calls = 0

    def diagnose(self, payload):
        result = self.diagnoses[min(self.diagnose_calls, len(self.diagnoses) - 1)]
        self.diagnose_calls += 1
        if isinstance(result, Exception):
            raise result
        return result

    def build_conclusion(self, payload):
        return InvestigationConclusion(
            summary="Production is below target and downtime is a supported contributor.",
            root_cause="Downtime contributed to the shortfall.",
            reliable_root_cause=True,
            observed_fact_evidence_ids=[],
            derived_metric_evidence_ids=["ev-production"],
            supported_hypothesis_ids=["hyp-1"],
            unresolved_uncertainties=[],
            confidence=ConfidenceLevel.MEDIUM,
        )

    def build_recommendation(self, payload):
        return InvestigationRecommendation(
            action_type=RecommendationAction.VERIFY_OPERATIONAL_CONDITION,
            description="Verify the recorded downtime condition with the shift supervisor.",
            rationale="The conclusion is evidence-linked but remains advisory.",
            evidence_ids=["ev-production", "invented-id"],
            human_validation_required=False,
        )


def _diagnosis(*, requests=None, can_conclude=True):
    return DiagnosisResult(
        hypotheses=[
            Hypothesis(
                hypothesis_id="hyp-1",
                statement="Recorded downtime may have contributed to the production gap.",
                supporting_evidence_ids=["ev-production", "invented-id"],
                contradictory_evidence_ids=[],
                confidence=ConfidenceLevel.MEDIUM,
                rationale="Production evidence indicates a gap.",
            )
        ],
        requested_information=requests or [],
        contradictions=[],
        can_conclude=can_conclude,
        confidence=ConfidenceLevel.MEDIUM,
        confidence_rationale="One evidence-backed hypothesis is available.",
        reasoning_summary="The production gap is observed; causality needs supporting context.",
    )


def _run(provider, *, max_iterations=3, tools=None):
    tools = tools or FakeTools()
    persisted = []
    runtime = InvestigationRuntime(
        session=object(),
        provider=provider,
        tools=tools,
        context_resolver=lambda session, trigger: _ctx(),
        context_reconstructor=lambda session, serialized: _ctx(),
        persister=lambda session, state: persisted.append(state),
    )
    graph = build_investigation_graph(runtime)
    result = graph.invoke(
        initial_state(
            _trigger(),
            max_iterations=max_iterations,
            provider=provider.provider_name,
            model=provider.model_name,
        )
    )
    return result, tools, persisted


def test_router_routes_without_additional_evidence():
    state = initial_state(_trigger(), max_iterations=3, provider="mock", model="mock")
    state["status"] = InvestigationStatus.ANALYZING
    state["iteration_count"] = 1
    assert route_after_analysis(state) == "build_conclusion"


def test_router_routes_to_controlled_evidence_gathering():
    state = initial_state(_trigger(), max_iterations=3, provider="mock", model="mock")
    state["status"] = InvestigationStatus.ANALYZING
    state["iteration_count"] = 1
    state["requested_information"] = [
        EvidenceRequest(request_type=EvidenceRequestType.DOWNTIME, reason="Check downtime")
    ]
    state["diagnosis"] = _diagnosis(
        requests=state["requested_information"], can_conclude=False
    )
    assert route_after_analysis(state) == "gather_requested_evidence"


def test_can_conclude_true_routes_to_conclusion_even_with_optional_request():
    state = initial_state(_trigger(), max_iterations=3, provider="mock", model="mock")
    request = EvidenceRequest(
        request_type=EvidenceRequestType.DOWNTIME,
        reason="Optional confirmation only",
    )
    state["status"] = InvestigationStatus.ANALYZING
    state["iteration_count"] = 1
    state["requested_information"] = [request]
    state["diagnosis"] = _diagnosis(requests=[request], can_conclude=True)

    assert route_after_analysis(state) == "build_conclusion"


def test_graph_completes_with_mocked_llm_and_sanitizes_citations():
    result, tools, persisted = _run(ScriptedProvider([_diagnosis()]))

    assert result["status"] == InvestigationStatus.COMPLETED
    assert result["iteration_count"] == 1
    assert tools.request_calls == 0
    assert result["hypotheses"][0].supporting_evidence_ids == ["ev-production"]
    assert result["recommendation"].evidence_ids == ["ev-production"]
    assert result["recommendation"].human_validation_required is True
    assert len(persisted) == 1


def test_graph_gathers_requested_evidence_then_reanalyzes():
    request = EvidenceRequest(
        request_type=EvidenceRequestType.DOWNTIME,
        reason="Need downtime context before concluding.",
    )
    provider = ScriptedProvider(
        [_diagnosis(requests=[request], can_conclude=False), _diagnosis(can_conclude=True)]
    )

    result, tools, _ = _run(provider)

    assert provider.diagnose_calls == 2
    assert tools.request_calls == 1
    assert len(result["evidence"]) == 2
    assert result["status"] == InvestigationStatus.COMPLETED


def test_iteration_limit_forces_explicit_uncertainty_and_no_root_cause():
    request = EvidenceRequest(
        request_type=EvidenceRequestType.DOWNTIME,
        reason="More downtime detail is still required.",
    )
    provider = ScriptedProvider([_diagnosis(requests=[request], can_conclude=False)])

    result, tools, _ = _run(provider, max_iterations=2)

    assert provider.diagnose_calls == 2
    assert tools.request_calls == 1
    assert result["iteration_limit_reached"] is True
    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert result["conclusion"].summary.startswith("Available evidence is insufficient")


def test_provider_failure_is_persisted_as_failed_investigation():
    result, _, persisted = _run(ScriptedProvider([RuntimeError("provider unavailable")]))

    assert result["status"] == InvestigationStatus.FAILED
    assert result["error"].stage == "analyze"
    assert result["completed_at"] is not None
    assert len(persisted) == 1


def test_fabricated_only_hypothesis_cannot_support_reliable_root_cause():
    diagnosis = _diagnosis()
    diagnosis.hypotheses[0].supporting_evidence_ids = ["fabricated-only"]

    result, _, _ = _run(ScriptedProvider([diagnosis]))

    assert result["hypotheses"][0].supporting_evidence_ids == []
    assert result["hypotheses"][0].confidence == ConfidenceLevel.LOW
    assert result["conclusion"].supported_hypothesis_ids == []
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY


def test_valid_part_of_contradiction_is_preserved_while_fabricated_id_is_removed():
    diagnosis = _diagnosis()
    diagnosis.contradictions = [
        Contradiction(
            description="The recorded state conflicts with the proposed cause.",
            evidence_ids=["ev-production", "fabricated-id"],
        )
    ]

    result, _, _ = _run(ScriptedProvider([diagnosis]))

    assert len(result["contradictions"]) == 1
    assert result["contradictions"][0].evidence_ids == ["ev-production"]


def test_cannot_conclude_without_requests_finishes_inconclusively():
    result, tools, _ = _run(
        ScriptedProvider([_diagnosis(can_conclude=False)]),
        max_iterations=5,
    )

    assert tools.request_calls == 0
    assert result["iteration_count"] == 1
    assert result["evidence_expansion_exhausted"] is True
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY


def test_repeated_unavailable_request_stops_before_iteration_limit():
    request = EvidenceRequest(
        request_type=EvidenceRequestType.DOWNTIME,
        reason="Need unavailable downtime detail.",
    )
    tools = FakeTools(requested_available=False)
    provider = ScriptedProvider([_diagnosis(requests=[request], can_conclude=False)])

    result, tools, _ = _run(provider, max_iterations=5, tools=tools)

    assert provider.diagnose_calls == 2
    assert tools.request_calls == 1
    assert result["iteration_limit_reached"] is False
    assert result["evidence_expansion_exhausted"] is True
    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY
    outcomes = [attempt.outcome.value for attempt in result["evidence_request_history"]]
    assert outcomes == ["UNAVAILABLE", "DUPLICATE_SKIPPED"]


def test_mocked_graph_execution_does_not_import_simulator_internals():
    before = {name for name in sys.modules if name == "simulator" or name.startswith("simulator.")}

    result, _, _ = _run(ScriptedProvider([_diagnosis()]))

    after = {name for name in sys.modules if name == "simulator" or name.startswith("simulator.")}
    assert after == before
    assert result["status"] == InvestigationStatus.COMPLETED


def test_runtime_does_not_cache_orm_operational_context():
    assert "operational_context" not in {field.name for field in fields(InvestigationRuntime)}


def test_context_reconstruction_failure_is_persisted_without_calling_llm():
    provider = ScriptedProvider([_diagnosis()])
    persisted = []
    runtime = InvestigationRuntime(
        session=object(),
        provider=provider,
        tools=FakeTools(),
        context_resolver=lambda session, trigger: _ctx(),
        context_reconstructor=lambda session, serialized: (_ for _ in ()).throw(
            RuntimeError("context cannot be reconstructed")
        ),
        persister=lambda session, state: persisted.append(state),
    )
    graph = build_investigation_graph(runtime)

    result = graph.invoke(
        initial_state(_trigger(), max_iterations=3, provider="mock", model="mock"),
        config={"recursion_limit": 25},
    )

    assert provider.diagnose_calls == 0
    assert result["status"] == InvestigationStatus.FAILED
    assert result["error"].stage == "gather_initial_evidence"
    assert len(persisted) == 1
