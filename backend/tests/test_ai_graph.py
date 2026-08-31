from datetime import date, datetime, time, timezone
from dataclasses import fields
import sys

from app.ai.contracts import (
    ConfidenceLevel,
    Contradiction,
    DiagnosisResult,
    DiagnosisStatus,
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


def _trigger(*, trigger_source=TriggerSource.USER_INVESTIGATE):
    return InvestigationTrigger(
        trigger_type=TriggerType.PRODUCTION_DEVIATION,
        trigger_source=trigger_source,
        subject=InvestigationSubject.PRODUCTION,
        source="test",
        site_id=1,
        shift_id=2,
        occurred_at=datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
    )


def _evidence(evidence_id="ev-production", metric="shift_production_summary"):
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=EvidenceKind.DERIVED_METRIC,
        source_tool="shift_production",
        source_service="app.services.operational.production.production_summary",
        metric=metric,
        value={
            "tonnage": 80,
            "target": 100,
            "windowStart": "2026-08-24T09:00:00+00:00",
        },
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
        self.diagnose_payloads = []
        self.recommend_payloads = []

    def diagnose(self, payload):
        self.diagnose_payloads.append(payload)
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
        self.recommend_payloads.append(payload)
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
                causal_depth=1,
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


def _run(provider, *, max_iterations=3, tools=None, trigger=None, debug=None):
    tools = tools or FakeTools()
    persisted = []
    runtime_kwargs = {}
    if debug is not None:
        runtime_kwargs["debug"] = debug
    runtime = InvestigationRuntime(
        session=object(),
        provider=provider,
        tools=tools,
        context_resolver=lambda session, trigger: _ctx(),
        context_reconstructor=lambda session, serialized: _ctx(),
        persister=lambda session, state: persisted.append(state),
        **runtime_kwargs,
    )
    graph = build_investigation_graph(runtime)
    result = graph.invoke(
        initial_state(
            trigger or _trigger(),
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

    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.PROBABLE
    assert result["conclusion"].reliable_root_cause is False
    assert result["iteration_count"] == 1
    assert tools.request_calls == 0
    assert result["hypotheses"][0].supporting_evidence_ids == ["ev-production"]
    assert result["recommendation"].evidence_ids == ["ev-production"]
    assert result["recommendation"].human_validation_required is True
    assert len(persisted) == 1


def test_initial_telemetry_trends_reach_the_provider_payload_unchanged():
    class TrendTools(FakeTools):
        def gather_initial(self, ctx, trigger):
            return [
                _evidence(),
                EvidenceItem(
                    evidence_id="ev-trends",
                    kind=EvidenceKind.DERIVED_METRIC,
                    source_tool="equipment_telemetry_trends",
                    source_service="app.oem.queries.get_equipment_signal_trends",
                    metric="equipment_telemetry_trends",
                    value={
                        "metrics": [
                            {
                                "metric": "oil_pressure_kpa",
                                "direction": "falling",
                                "representativeSamples": [
                                    {"ts": "2026-08-24T09:45:00Z", "value": 410},
                                    {"ts": "2026-08-24T09:55:00Z", "value": 275},
                                ],
                            }
                        ]
                    },
                    equipment_id=7,
                ),
            ]

    provider = ScriptedProvider([_diagnosis()])
    _run(provider, tools=TrendTools())

    payload_evidence = provider.diagnose_payloads[0]["evidence"]
    trend = next(item for item in payload_evidence if item["evidence_id"] == "ev-trends")
    assert trend["value"]["metrics"][0]["representativeSamples"][0]["value"] == 410
    assert "EQUIPMENT_TELEMETRY_TRENDS" in provider.diagnose_payloads[0][
        "approvedEvidenceRequestTypes"
    ]
    assert "ROAD_NETWORK_CONTEXT" in provider.diagnose_payloads[0]["approvedEvidenceRequestTypes"]
    assert "WEATHER_CONTEXT" in provider.diagnose_payloads[0]["approvedEvidenceRequestTypes"]
    assert provider.diagnose_payloads[0]["approvedTelemetryMetricGroups"] == [
        "equipment",
        "mechanical",
        "fuel",
        "connectivity",
    ]


def test_recommendation_stage_attaches_operator_feedback_not_as_fact(monkeypatch):
    feedback = EvidenceItem(
        evidence_id="ev-feedback",
        kind=EvidenceKind.OPERATOR_FEEDBACK,
        source_tool="operator_feedback_memory",
        source_service="app.ai.feedback.retrieve_operator_feedback",
        metric="site_decision_history",
        value={"decisionType": "REJECTED", "authoritativeFactsWin": True},
        notes="Historical operator decision",
    )
    monkeypatch.setattr("app.ai.nodes.retrieve_operator_feedback", lambda session, state: [feedback])
    provider = ScriptedProvider([_diagnosis()])
    result, _, _ = _run(provider)
    kinds = [item["kind"] for item in provider.recommend_payloads[0]["evidence"]]
    assert "OPERATOR_FEEDBACK" in kinds
    assert result["evidence"][-1].kind == EvidenceKind.OPERATOR_FEEDBACK
    assert result["evidence"][-1].kind != EvidenceKind.FACT
    assert result["evidence"][-1].source_service.endswith("retrieve_operator_feedback")


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
    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.PROBABLE


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
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert result["conclusion"].summary.startswith("Available evidence is insufficient")
    assert any("iteration" in item.casefold() for item in result["conclusion"].unresolved_uncertainties)


def test_provider_failure_is_persisted_as_failed_investigation(caplog):
    result, _, persisted = _run(ScriptedProvider([RuntimeError("private provider response")]))

    assert result["status"] == InvestigationStatus.FAILED
    assert result["error"].stage == "analyze"
    assert result["completed_at"] is not None
    assert len(persisted) == 1
    assert "private provider response" not in result["error"].message
    assert result["investigation_id"] in caplog.text
    assert "stage=analyze" in caplog.text


def test_fabricated_only_hypothesis_cannot_support_reliable_root_cause():
    diagnosis = _diagnosis()
    diagnosis.hypotheses[0].supporting_evidence_ids = ["fabricated-only"]

    result, _, _ = _run(ScriptedProvider([diagnosis]))

    assert result["hypotheses"][0].supporting_evidence_ids == []
    assert result["hypotheses"][0].confidence == ConfidenceLevel.LOW
    assert result["conclusion"].supported_hypothesis_ids == []
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert result["conclusion"].summary.startswith("Available evidence is insufficient")
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
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY


def test_uncertain_result_cannot_repeat_provider_confirmation_language():
    class ContradictoryWordingProvider(ScriptedProvider):
        def build_conclusion(self, payload):
            return InvestigationConclusion(
                summary=(
                    "Evidence is insufficient, while confirming the reliability of the diagnosis."
                ),
                root_cause="A confirmed component failure",
                reliable_root_cause=True,
                derived_metric_evidence_ids=["ev-production"],
                supported_hypothesis_ids=["hyp-1"],
                confidence=ConfidenceLevel.HIGH,
            )

        def build_recommendation(self, payload):
            return InvestigationRecommendation(
                action_type=RecommendationAction.INSPECT_EQUIPMENT,
                description="Act on the confirmed diagnosis.",
                rationale="This confirms the reliable root cause.",
                evidence_ids=["ev-production"],
            )

    result, _, _ = _run(
        ContradictoryWordingProvider([_diagnosis(can_conclude=False)])
    )

    combined = " ".join(
        [
            result["conclusion"].summary,
            result["recommendation"].description,
            result["recommendation"].rationale,
        ]
    ).casefold()
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert "confirming" not in combined
    assert "confirmed diagnosis" not in combined
    assert "did not establish a reliable root cause" in combined


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
    assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY


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


def _fault_evidence():
    return EvidenceItem(
        evidence_id="ev-fault",
        kind=EvidenceKind.FACT,
        source_tool="oem_diagnostics",
        source_service="app.oem.queries.list_equipment_diagnostics",
        metric="oem_diagnostics",
        value={"code": "LUBE-FAULT", "confirmed": True},
        site_id=1,
        shift_id=2,
        equipment_id=7,
        observed_at=_ctx().sim_now,
        metadata={"causalConfirmation": True},
    )


class ConfirmationTools(FakeTools):
    def gather_initial(self, ctx, trigger):
        return [_fault_evidence()]


class ConfirmedProvider(ScriptedProvider):
    def diagnose(self, payload):
        self.diagnose_payloads.append(payload)
        self.diagnose_calls += 1
        return DiagnosisResult(
            hypotheses=[
                Hypothesis(
                    hypothesis_id="hyp-1",
                    statement="A confirmed lubrication-circuit fault stopped the equipment.",
                    supporting_evidence_ids=["ev-fault"],
                    contradictory_evidence_ids=[],
                    confidence=ConfidenceLevel.HIGH,
                    causal_depth=2,
                    rationale="OEM diagnostic confirmation is present.",
                )
            ],
            requested_information=[],
            contradictions=[],
            can_conclude=True,
            confidence=ConfidenceLevel.HIGH,
            confidence_rationale="Authoritative confirmation is present.",
            reasoning_summary="Direct diagnostic confirmation supports the cause.",
        )

    def build_conclusion(self, payload):
        return InvestigationConclusion(
            summary="Authoritative evidence supports a lubrication-circuit fault.",
            diagnosis_status=DiagnosisStatus.CONFIRMED,
            root_cause="A confirmed lubrication-circuit fault stopped the equipment.",
            reliable_root_cause=True,
            observed_fact_evidence_ids=["ev-fault"],
            supported_hypothesis_ids=["hyp-1"],
            unresolved_uncertainties=[],
            confidence=ConfidenceLevel.HIGH,
        )


def test_authoritative_confirmation_yields_confirmed_root_cause():
    result, _, _ = _run(ConfirmedProvider([_diagnosis()]), tools=ConfirmationTools())

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.CONFIRMED
    assert result["conclusion"].reliable_root_cause is True
    assert result["conclusion"].root_cause is not None
    assert result["status"] == InvestigationStatus.COMPLETED
    assert "authoritative" in result["conclusion"].summary.casefold()


def test_probable_keeps_reliable_root_cause_false():
    result, _, _ = _run(ScriptedProvider([_diagnosis()]))

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.PROBABLE
    assert result["conclusion"].reliable_root_cause is False
    assert "downtime" in result["conclusion"].root_cause.casefold()
    assert not result["conclusion"].summary.startswith("Available evidence is insufficient")
    assert any("not confirmed" in item.casefold() for item in result["conclusion"].unresolved_uncertainties)


def test_invalid_confirmed_without_authoritative_evidence_is_downgraded():
    class OverconfidentProvider(ScriptedProvider):
        def build_conclusion(self, payload):
            return InvestigationConclusion(
                summary="This is a confirmed component failure.",
                diagnosis_status=DiagnosisStatus.CONFIRMED,
                root_cause="A confirmed component failure",
                reliable_root_cause=True,
                derived_metric_evidence_ids=["ev-production"],
                supported_hypothesis_ids=["hyp-1"],
                confidence=ConfidenceLevel.HIGH,
            )

    result, _, _ = _run(OverconfidentProvider([_diagnosis()]))

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.PROBABLE
    assert result["conclusion"].reliable_root_cause is False
    assert "confirmed component failure" not in result["conclusion"].summary.casefold()


def test_llm_confirmed_with_fabricated_evidence_cannot_be_probable():
    class FabricatedConfirmedProvider(ScriptedProvider):
        def build_conclusion(self, payload):
            return InvestigationConclusion(
                summary="Confirmed from invented evidence.",
                diagnosis_status=DiagnosisStatus.CONFIRMED,
                root_cause="Invented component failure",
                reliable_root_cause=True,
                observed_fact_evidence_ids=["ev-invented"],
                supported_hypothesis_ids=["hyp-1"],
                confidence=ConfidenceLevel.HIGH,
            )

    diagnosis = _diagnosis()
    diagnosis.hypotheses[0].supporting_evidence_ids = ["ev-invented"]
    result, _, _ = _run(FabricatedConfirmedProvider([diagnosis]))

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].reliable_root_cause is False
    assert result["conclusion"].root_cause is None
    assert result["conclusion"].summary.startswith("Available evidence is insufficient")


def test_unsupported_hypothesis_cannot_produce_probable():
    diagnosis = _diagnosis()
    diagnosis.hypotheses[0].supporting_evidence_ids = []
    result, _, _ = _run(ScriptedProvider([diagnosis]))

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].root_cause is None
    assert result["conclusion"].reliable_root_cause is False


def test_low_confidence_support_is_inconclusive():
    diagnosis = _diagnosis()
    diagnosis.hypotheses[0].confidence = ConfidenceLevel.LOW
    result, _, _ = _run(ScriptedProvider([diagnosis]))

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].summary.startswith("Available evidence is insufficient")


def test_contradictory_evidence_downgrades_to_inconclusive():
    diagnosis = _diagnosis()
    diagnosis.contradictions = [
        Contradiction(
            description="The recorded state conflicts with the proposed cause.",
            evidence_ids=["ev-production"],
        )
    ]
    result, _, _ = _run(ScriptedProvider([diagnosis]))

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].root_cause is None
    assert result["conclusion"].summary.startswith("Available evidence is insufficient")


def test_equal_competing_hypotheses_are_inconclusive():
    diagnosis = DiagnosisResult(
        hypotheses=[
            Hypothesis(
                hypothesis_id="hyp-1",
                statement="Downtime contributed to the shortfall.",
                supporting_evidence_ids=["ev-production"],
                contradictory_evidence_ids=[],
                confidence=ConfidenceLevel.MEDIUM,
                causal_depth=1,
                rationale="Production evidence indicates a gap.",
            ),
            Hypothesis(
                hypothesis_id="hyp-2",
                statement="An operator delay contributed to the shortfall.",
                supporting_evidence_ids=["ev-production"],
                contradictory_evidence_ids=[],
                confidence=ConfidenceLevel.MEDIUM,
                causal_depth=1,
                rationale="The same evidence also fits an operational delay.",
            ),
        ],
        requested_information=[],
        contradictions=[],
        can_conclude=True,
        confidence=ConfidenceLevel.MEDIUM,
        confidence_rationale="Two equally supported explanations remain.",
        reasoning_summary="The evidence cannot discriminate between the two hypotheses.",
    )
    result, _, _ = _run(ScriptedProvider([diagnosis]))

    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert result["conclusion"].root_cause is None
    assert "discriminate" in " ".join(result["conclusion"].unresolved_uncertainties).casefold()


def test_automatic_and_manual_triggers_share_diagnosis_semantics():
    for source in (TriggerSource.USER_INVESTIGATE, TriggerSource.AUTOMATIC_MONITORING):
        result, _, _ = _run(
            ScriptedProvider([_diagnosis()]),
            trigger=_trigger(trigger_source=source),
        )
        assert result["trigger"].trigger_source == source
        assert result["conclusion"].diagnosis_status == DiagnosisStatus.PROBABLE
        assert result["conclusion"].reliable_root_cause is False
        assert result["status"] == InvestigationStatus.COMPLETED_WITH_UNCERTAINTY


def test_inconclusive_recommendation_keeps_insufficient_root_cause_wording():
    diagnosis = _diagnosis()
    diagnosis.hypotheses[0].supporting_evidence_ids = ["fabricated-only"]
    result, _, _ = _run(ScriptedProvider([diagnosis]))
    combined = " ".join(
        [
            result["conclusion"].summary,
            result["recommendation"].description,
            result["recommendation"].rationale,
        ]
    )
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert combined.startswith("Available evidence is insufficient") or (
        "Available evidence is insufficient" in result["conclusion"].summary
    )
    assert "did not establish a reliable root cause" in result["recommendation"].rationale
