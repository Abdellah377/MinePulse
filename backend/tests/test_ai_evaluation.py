from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from ai_eval.cases import EVALUATION_CASES, get_case
from ai_eval.contracts import EvaluationOutcome
from ai_eval.providers import DeterministicEvaluationProvider, MockProfile
from ai_eval.runner import assert_ground_truth_isolated, report_from_result
from ai_eval.scoring import detect_data_quality_warnings, evaluate_result
from app.ai.contracts import (
    ConfidenceLevel,
    Contradiction,
    DiagnosisResult,
    EvidenceItem,
    EvidenceKind,
    EvidenceRequestType,
    Hypothesis,
    InvestigationConclusion,
    InvestigationError,
    InvestigationRecommendation,
    InvestigationResult,
    InvestigationStatus,
    InvestigationTrigger,
    RecommendationAction,
    TriggerSource,
)
from app.ai.llm.provider import ProviderResponseError


NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def _trigger() -> InvestigationTrigger:
    return InvestigationTrigger(
        trigger_type="EQUIPMENT_ANOMALY",
        trigger_source=TriggerSource.USER_INVESTIGATE,
        source="ai-evaluation",
        source_record_id=f"ai-eval-{uuid4()}",
        site_id=1,
        shift_id=2,
        equipment_id=3,
        occurred_at=NOW,
        payload={"evaluation_run": True},
    )


def _result(
    *,
    statement: str = "The equipment stop remains unexplained.",
    reliable: bool = False,
    citation: str = "ev-fact",
    status: InvestigationStatus = InvestigationStatus.COMPLETED_WITH_UNCERTAINTY,
    error: InvestigationError | None = None,
    evidence: list[EvidenceItem] | None = None,
    contradictions: list[Contradiction] | None = None,
) -> InvestigationResult:
    items = evidence or [
        EvidenceItem(
            evidence_id="ev-fact",
            kind=EvidenceKind.FACT,
            source_tool="site_alerts",
            source_service="app.services.operational.alerts.list_site_alerts",
            metric="active_site_alerts",
            value=[{"alertType": "UNEXPLAINED_STOP"}],
            site_id=1,
            shift_id=2,
            equipment_id=3,
            observed_at=NOW,
            source_record_ids=["alert:4"],
        ),
        EvidenceItem(
            evidence_id="ev-metric",
            kind=EvidenceKind.DERIVED_METRIC,
            source_tool="fleet_snapshot",
            source_service="app.services.operational.equipment.build_fleet_bulk_context",
            metric="fleet_snapshot",
            value=[{"equipmentId": 3, "currentState": "STOPPED_OTHER"}],
            site_id=1,
            shift_id=2,
            equipment_id=3,
            observed_at=NOW,
            source_record_ids=["equipment:3"],
        ),
        EvidenceItem(
            evidence_id="ev-timeline",
            kind=EvidenceKind.FACT,
            source_tool="equipment_timeline",
            source_service="app.services.operational.timeline.timeline_for_shift",
            metric="equipment_state_timeline",
            value=[],
            site_id=1,
            shift_id=2,
            equipment_id=3,
            observed_at=NOW,
        ),
    ]
    hypothesis = Hypothesis(
        hypothesis_id="hyp-1",
        statement=statement,
        supporting_evidence_ids=[citation],
        confidence=ConfidenceLevel.HIGH if reliable else ConfidenceLevel.LOW,
        rationale="Evaluation fixture rationale.",
    )
    conclusion = InvestigationConclusion(
        summary=statement,
        root_cause=statement if reliable else None,
        reliable_root_cause=reliable,
        observed_fact_evidence_ids=[citation],
        supported_hypothesis_ids=["hyp-1"],
        unresolved_uncertainties=[] if reliable else ["Cause is not established."],
        confidence=ConfidenceLevel.HIGH if reliable else ConfidenceLevel.LOW,
    )
    recommendation = InvestigationRecommendation(
        action_type=RecommendationAction.VERIFY_OPERATIONAL_CONDITION,
        description="Have an operator verify the condition before acting.",
        rationale="Evidence is limited.",
        evidence_ids=[citation] if citation == "ev-fact" else [],
        human_validation_required=True,
    )
    return InvestigationResult(
        investigation_id=uuid4(),
        trigger=_trigger(),
        evidence=items,
        hypotheses=[hypothesis],
        contradictions=contradictions or [],
        conclusion=conclusion,
        recommendation=recommendation,
        iteration_count=1,
        max_iterations=3,
        status=status,
        error=error,
        started_at=NOW,
        completed_at=NOW,
        graph_version="1",
        provider="evaluation-mock",
        model="deterministic-no-llm",
    )


@pytest.mark.ai_eval
def test_ground_truth_is_not_present_in_investigation_input():
    case = get_case("clear_equipment_failure")
    trigger = _trigger()
    assert_ground_truth_isolated(case, trigger)
    payload = trigger.model_dump_json().casefold()
    assert case.case_id not in payload
    assert case.ground_truth.scenario_name not in payload
    assert case.ground_truth.label.value.casefold() not in payload
    assert "ground_truth" not in payload
    assert "reviewer" not in payload


@pytest.mark.ai_eval
def test_ground_truth_leak_guard_rejects_scenario_metadata():
    case = get_case("connectivity_loss")
    trigger = _trigger().model_copy(update={"payload": {"scenario": "comm_loss"}})
    with pytest.raises(RuntimeError, match="ground truth leaked"):
        assert_ground_truth_isolated(case, trigger)


@pytest.mark.ai_eval
def test_unsupported_reliable_root_cause_is_rejected_by_metrics():
    case = get_case("clear_equipment_failure").model_copy(
        update={"expected_evidence_tools": ["fleet_snapshot", "site_alerts"]}
    )
    result = _result(
        statement="Confirmed mechanical failure.",
        reliable=True,
        citation="ev-fabricated",
    )
    checks, _, outcome = evaluate_result(case, result)
    assert not next(c for c in checks if c.check_id == "evidence_ids_are_valid").passed
    assert not next(c for c in checks if c.check_id == "reliable_root_cause_is_supported").passed
    assert outcome == EvaluationOutcome.AI_REASONING_FAILURE


@pytest.mark.ai_eval
def test_inconclusive_case_accepts_explicit_uncertainty():
    case = get_case("ambiguous_stop")
    checks, warnings, outcome = evaluate_result(case, _result())
    assert not warnings
    assert next(c for c in checks if c.check_id == "expected_reliability").passed
    assert next(c for c in checks if c.check_id == "expected_confidence").passed
    assert outcome == EvaluationOutcome.PASS


@pytest.mark.ai_eval
def test_contradictions_are_reported_with_real_provenance():
    result = _result(
        contradictions=[
            Contradiction(
                description="Alert indicates a stop while another record says active.",
                evidence_ids=["ev-fact", "ev-metric"],
            )
        ]
    )
    checks, _, _ = evaluate_result(get_case("ambiguous_stop"), result)
    assert result.contradictions[0].evidence_ids == ["ev-fact", "ev-metric"]
    assert next(
        c for c in checks if c.check_id == "contradictions_preserve_valid_provenance"
    ).passed


@pytest.mark.ai_eval
def test_data_quality_overlap_is_classified_separately():
    timeline = EvidenceItem(
        evidence_id="ev-timeline",
        kind=EvidenceKind.FACT,
        source_tool="equipment_timeline",
        source_service="app.services.operational.timeline.timeline_for_shift",
        metric="equipment_state_timeline",
        value=[
            {"id": "state:1", "equipmentId": "TRK-012", "state": "ACTIVE", "start": "2026-08-26T06:00:00Z", "end": "2026-08-26T06:20:00Z"},
            {"id": "state:2", "equipmentId": "TRK-012", "state": "STOPPED_OTHER", "start": "2026-08-26T06:15:00Z", "end": "2026-08-26T06:30:00Z"},
        ],
    )
    result = _result(evidence=[
        timeline,
        EvidenceItem(evidence_id="ev-fact", kind="FACT", source_tool="site_alerts", source_service="app.services.operational.alerts.list_site_alerts", metric="active_site_alerts", value=[]),
        EvidenceItem(evidence_id="ev-metric", kind="DERIVED_METRIC", source_tool="fleet_snapshot", source_service="app.services.operational.equipment.build_fleet_bulk_context", metric="fleet_snapshot", value=[]),
    ])
    warnings = detect_data_quality_warnings(result)
    _, _, outcome = evaluate_result(get_case("ambiguous_stop"), result)
    assert warnings and "Overlapping" in warnings[0]
    assert outcome == EvaluationOutcome.DATA_QUALITY_WARNING


@pytest.mark.ai_eval
def test_causal_case_scores_timestamped_preincident_trend():
    incident_at = NOW.replace(hour=6, minute=10)
    evidence = [
        EvidenceItem(
            evidence_id="ev-fact",
            kind="FACT",
            source_tool="site_alerts",
            source_service="app.services.operational.alerts.list_site_alerts",
            metric="active_site_alerts",
            value=[
                {
                    "alertId": 9,
                    "createdAt": NOW.replace(hour=5, minute=50).isoformat(),
                    "alertType": "EQUIPMENT_MECHANICAL_STOP",
                },
                {
                    "alertId": 10,
                    "createdAt": incident_at.isoformat(),
                    "alertType": "EQUIPMENT_MECHANICAL_STOP",
                }
            ],
        ),
        EvidenceItem(
            evidence_id="ev-metric",
            kind="DERIVED_METRIC",
            source_tool="fleet_snapshot",
            source_service="app.services.operational.equipment.build_fleet_bulk_context",
            metric="fleet_snapshot",
            value=[{"code": "TRK-001", "currentState": "STOPPED_MECHANICAL"}],
        ),
        EvidenceItem(
            evidence_id="ev-diag",
            kind="DERIVED_METRIC",
            source_tool="oem_diagnostics",
            source_service="app.oem.queries.diagnostic_parameters",
            metric="oem_diagnostic_parameters",
            value=[{"parameterKey": "oil_pressure_kpa", "min": 140, "max": 410}],
            metadata={
                "signalHistory": {
                    "points": [
                        {"ts": NOW.replace(hour=6, minute=1).isoformat(), "oil_pressure_kpa": 410},
                        {"ts": NOW.replace(hour=6, minute=4).isoformat(), "oil_pressure_kpa": 330},
                        {"ts": NOW.replace(hour=6, minute=7).isoformat(), "oil_pressure_kpa": 220},
                    ]
                }
            },
        ),
    ]
    result = _result(
        statement="Lubrication and oil pressure degradation preceded the stop.",
        reliable=True,
        citation="ev-diag",
        evidence=evidence,
        status=InvestigationStatus.COMPLETED,
    )
    checks, warnings, outcome = evaluate_result(
        get_case("causal_lubrication_degradation"), result
    )
    assert next(c for c in checks if c.check_id == "symptom_trend_predates_incident").passed
    assert not warnings
    assert outcome == EvaluationOutcome.PASS


@pytest.mark.ai_eval
def test_causal_case_reports_wrong_temporal_direction_as_data_quality():
    evidence = [
        EvidenceItem(
            evidence_id="ev-fact",
            kind="FACT",
            source_tool="site_alerts",
            source_service="app.services.operational.alerts.list_site_alerts",
            metric="active_site_alerts",
            value=[
                {
                    "createdAt": NOW.replace(hour=6, minute=10).isoformat(),
                    "alertType": "EQUIPMENT_MECHANICAL_STOP",
                }
            ],
        ),
        EvidenceItem(
            evidence_id="ev-metric",
            kind="DERIVED_METRIC",
            source_tool="fleet_snapshot",
            source_service="app.services.operational.equipment.build_fleet_bulk_context",
            metric="fleet_snapshot",
            value=[],
        ),
        EvidenceItem(
            evidence_id="ev-diag",
            kind="DERIVED_METRIC",
            source_tool="oem_diagnostics",
            source_service="app.oem.queries.diagnostic_parameters",
            metric="oem_diagnostic_parameters",
            value=[],
            metadata={
                "signalHistory": {
                    "points": [
                        {"ts": NOW.replace(hour=6, minute=1).isoformat(), "oil_pressure_kpa": 200},
                        {"ts": NOW.replace(hour=6, minute=3).isoformat(), "oil_pressure_kpa": 300},
                        {"ts": NOW.replace(hour=6, minute=5).isoformat(), "oil_pressure_kpa": 410},
                    ]
                }
            },
        ),
    ]
    result = _result(
        statement="Lubrication degradation preceded the stop.",
        reliable=True,
        citation="ev-diag",
        evidence=evidence,
        status=InvestigationStatus.COMPLETED,
    )
    _, warnings, outcome = evaluate_result(
        get_case("causal_lubrication_degradation"), result
    )
    assert any("Temporal scenario evidence" in warning for warning in warnings)
    assert outcome == EvaluationOutcome.DATA_QUALITY_WARNING


@pytest.mark.ai_eval
def test_provider_failure_has_its_own_classification():
    result = _result(
        status=InvestigationStatus.FAILED,
        error=InvestigationError(
            stage="analyze",
            error_type="ProviderResponseError",
            message="Investigation failed at analyze. Consult server logs.",
        ),
    )
    _, _, outcome = evaluate_result(get_case("ambiguous_stop"), result)
    assert outcome == EvaluationOutcome.PROVIDER_FAILURE


@pytest.mark.ai_eval
def test_programming_failure_is_not_misclassified_as_provider_failure():
    result = _result(
        status=InvestigationStatus.FAILED,
        error=InvestigationError(
            stage="analyze",
            error_type="TypeError",
            message="Investigation failed at analyze. Consult server logs.",
        ),
    )
    _, _, outcome = evaluate_result(get_case("ambiguous_stop"), result)
    assert outcome == EvaluationOutcome.INTEGRATION_FAILURE


@pytest.mark.ai_eval
@pytest.mark.parametrize(
    "profile",
    [
        MockProfile.SUCCESS,
        MockProfile.REQUEST_MORE_EVIDENCE,
        MockProfile.INCONCLUSIVE,
        MockProfile.FABRICATED_CITATION,
    ],
)
def test_mock_provider_modes_are_schema_valid_and_cost_nothing(profile):
    provider = DeterministicEvaluationProvider(
        profile=profile,
        request_type=EvidenceRequestType.EQUIPMENT_TIMELINE,
    )
    diagnosis = provider.diagnose(
        {
            "trigger": _trigger().model_dump(mode="json"),
            "evidence": [
                EvidenceItem(
                    kind="FACT",
                    source_tool="site_alerts",
                    source_service="service",
                    metric="alerts",
                    value=[],
                ).model_dump(mode="json")
            ],
            "investigationRound": 1,
        }
    )
    assert isinstance(diagnosis, DiagnosisResult)
    assert provider.provider_name == "evaluation-mock"


@pytest.mark.ai_eval
def test_mock_provider_failure_is_deterministic():
    provider = DeterministicEvaluationProvider(profile=MockProfile.PROVIDER_FAILURE)
    with pytest.raises(ProviderResponseError):
        provider.diagnose({"trigger": {}, "evidence": []})


@pytest.mark.ai_eval
def test_report_is_json_serializable_and_contains_trace():
    case = get_case("ambiguous_stop")
    result = _result()
    report = report_from_result(
        case,
        result.trigger,
        result,
        reasoning_mode="MOCKED_PIPELINE",
        persisted_ok=True,
    )
    restored = type(report).model_validate_json(report.model_dump_json())
    assert restored == report
    assert report.evidence[0].source_service.startswith("app.services.operational")
    assert report.hypotheses and report.conclusion and report.recommendation
    assert report.quality_levels["LEVEL_1_INTEGRATION"] is True
    assert report.quality_levels["LEVEL_2_EVIDENCE_REASONING"] is None


@pytest.mark.ai_eval
def test_production_ai_has_no_simulator_import_and_eval_does_not_leak_back():
    backend = Path(__file__).resolve().parents[1]
    production = backend / "app" / "ai"
    for path in production.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not item.name.startswith("simulator") for item in node.names)
                assert all(not item.name.startswith("ai_eval") for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("simulator")
                assert not (node.module or "").startswith("ai_eval")
    runner = (backend / "ai_eval" / "runner.py").read_text(encoding="utf-8")
    assert "simulator" not in runner.casefold()


def test_case_catalog_contains_three_control_conditions():
    assert {
        "clear_equipment_failure",
        "connectivity_loss",
        "ambiguous_stop",
    }.issubset(EVALUATION_CASES)
    assert {
        "causal_lubrication_degradation",
        "causal_cooling_degradation",
        "causal_tyre_degradation",
        "causal_communication_degradation",
        "causal_loader_bottleneck",
    }.issubset(EVALUATION_CASES)
