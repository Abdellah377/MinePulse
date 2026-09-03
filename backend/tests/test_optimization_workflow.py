from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.ai.llm.provider import LLMProviderError
from app.ai.optimization.workflow import MAX_OPTIMIZATION_PASSES, create_optimization_workflow
from app.db.models import Site
from app.optimization.compose import NO_CHANGE_OPERATOR_COPY, REVIEW_UNAVAILABLE_COPY
from app.optimization.contracts import (
    OptimizationPlannerDecision,
    OptimizationReview,
    OptimizerId,
    ProblemType,
    ReviewStatus,
    WorkflowStatus,
    payload_contains_forbidden_numeric_facts,
)
from app.optimization.inputs import TrustedOptimizationInput
from app.services.operational.context import OperationalContext


SITE_ID = 17


def _alert():
    return SimpleNamespace(
        alert_id=42,
        alert_type="CONGESTION_RISK",
        equipment_id=1,
        zone_id=None,
        metadata_={},
    )


def _ctx():
    site = Site(site_id=SITE_ID, code="MP-SIM-01", name="Site", active=True)
    return OperationalContext(
        site=site,
        shift=None,
        sim_now=datetime(2026, 8, 31, 12, tzinfo=timezone.utc),
        shift_window_start=datetime(2026, 8, 31, 6, tzinfo=timezone.utc),
        shift_window_end=datetime(2026, 8, 31, 14, tzinfo=timezone.utc),
    )


def _trusted():
    truck = SimpleNamespace(equipment_id=1, code="TRK-1")
    assignment = SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=2, assignment_id=9)
    return TrustedOptimizationInput(
        truck=truck,
        assignment=assignment,
        loaders=[SimpleNamespace(equipment_id=10, code="LD-1")],
        roads=[],
        zone_codes={1: "L1", 2: "D1"},
        loading={"loaders": [], "sourceRecordIds": []},
        origin_code="L1",
        dest_code="D1",
        loader_zones={10: "L1"},
        candidate_loader_ids=[10],
        mechanical_risk_loader_ids=set(),
        planner_facts={
            "alertType": "CONGESTION_RISK",
            "hasQueueCondition": True,
            "hasRoadRestrictionOrBlockage": False,
            "hasMechanicalRiskAlert": False,
            "registeredOptimizers": ["DISPATCH_LOADER", "ROUTE"],
            "evidenceIds": ["alert-42"],
        },
        snapshot_fields={"truckCode": "TRK-1"},
        evidence_ids=["alert-42"],
    )


def _candidates():
    return [
        {
            "candidateId": "c-1",
            "loaderId": 10,
            "loaderCode": "LD-1",
            "destZoneCode": "D1",
            "originZoneCode": "L1",
            "roadIds": ["R-1"],
            "distanceKm": 2.0,
            "travelMinutes": 4.0,
            "waitMinutes": 8.0,
            "score": 12.0,
            "constraintNotes": [],
            "isCurrent": True,
            "rankReason": "score",
            "rank": 2,
        },
        {
            "candidateId": "c-2",
            "loaderId": 11,
            "loaderCode": "LD-2",
            "destZoneCode": "D1",
            "originZoneCode": "L2",
            "roadIds": ["R-2"],
            "distanceKm": 2.2,
            "travelMinutes": 4.4,
            "waitMinutes": 0.0,
            "score": 4.4,
            "constraintNotes": [],
            "isCurrent": False,
            "rankReason": "score",
            "rank": 1,
        },
    ]


class FakeOptProvider:
    provider_name = "fake"
    model_name = "test-model"

    def __init__(
        self,
        decision=None,
        reviews=None,
        plan_error=None,
        review_error=None,
        remaining_seconds=None,
        timeout_seconds=15,
        plan_cost=0,
        review_cost=0,
    ):
        self.decision = decision or OptimizationPlannerDecision(
            selected_optimizers=[OptimizerId.DISPATCH_LOADER],
            problem_type=ProblemType.CONGESTION_RISK,
        )
        self.reviews = list(reviews or [OptimizationReview(status=ReviewStatus.APPROVED)])
        self.plan_error = plan_error
        self.review_error = review_error
        self.plan_calls = []
        self.review_calls = []
        self.plan_cost = plan_cost
        self.review_cost = review_cost
        if remaining_seconds is not None:
            self._remaining_seconds = remaining_seconds
            self._timeout_seconds = timeout_seconds

    def plan_optimization(self, payload):
        self.plan_calls.append(payload)
        if getattr(self, "_remaining_seconds", None) is not None:
            self._remaining_seconds -= self.plan_cost
        if self.plan_error:
            raise self.plan_error
        assert payload_contains_forbidden_numeric_facts(payload) is False
        return self.decision

    def review_optimization(self, payload):
        self.review_calls.append(payload)
        if getattr(self, "_remaining_seconds", None) is not None:
            self._remaining_seconds -= self.review_cost
        if self.review_error:
            raise self.review_error
        if not self.reviews:
            return OptimizationReview(status=ReviewStatus.APPROVED)
        return self.reviews.pop(0)


def _patch_common(monkeypatch, *, engines=None, persist=None, fallback=None):
    engine_calls = []

    def fake_engines(**kwargs):
        engine_calls.append(kwargs)
        return engines if engines is not None else _candidates()

    captured = {}

    def fake_persist(*args, **kwargs):
        captured.update(kwargs)
        return {
            "runId": "run-1",
            "alertId": "alert-42",
            "outcome": kwargs.get("outcome"),
            "candidates": kwargs.get("candidates"),
            "recommendedCandidateId": kwargs.get("recommended_candidate_id"),
            "workflowStatus": (kwargs.get("snapshot") or {}).get("workflow", {}).get("workflowStatus"),
            "displayedCandidateIds": (kwargs.get("snapshot") or {}).get("workflow", {}).get("displayedCandidateIds"),
            "explanation": kwargs.get("explanation"),
            "snapshot": kwargs.get("snapshot"),
        }

    def fake_fallback(*args, **kwargs):
        captured["fallback"] = kwargs.get("extra_snapshot") or True
        return {"runId": "det-1", "workflowStatus": "DETERMINISTIC_ONLY", "outcome": "FEASIBLE", "candidates": _candidates()}

    monkeypatch.setattr("app.ai.optimization.workflow.get_site_alert_or_404", lambda *_a, **_k: _alert())
    monkeypatch.setattr("app.ai.optimization.workflow.eligibility_for_alert", lambda *_a, **_k: "OPTIMIZABLE")
    monkeypatch.setattr("app.ai.optimization.workflow.build_trusted_optimization_input", lambda *_a, **_k: _trusted())
    monkeypatch.setattr("app.ai.optimization.workflow.find_investigations", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "app.ai.optimization.workflow.get_weather_context",
        lambda *_a, **_k: SimpleNamespace(status=SimpleNamespace(value="UNAVAILABLE"), unavailableReason="test", current=None),
    )
    monkeypatch.setattr("app.ai.optimization.workflow.execute_selected_engines", fake_engines)
    monkeypatch.setattr("app.ai.optimization.workflow.persist_evaluated_run", persist or fake_persist)
    monkeypatch.setattr("app.ai.optimization.workflow.create_optimization_run", fallback or fake_fallback)
    monkeypatch.setattr("app.ai.optimization.workflow.investigation_gate.semaphore", lambda *_a, **_k: MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False))
    return engine_calls, captured


def test_workflow_planner_failure_falls_back_to_deterministic(monkeypatch):
    _patch_common(monkeypatch)
    payload = create_optimization_workflow(
        MagicMock(),
        _ctx(),
        "alert-42",
        provider=FakeOptProvider(plan_error=LLMProviderError("down")),
    )
    assert payload["workflowStatus"] == "DETERMINISTIC_ONLY"


def test_workflow_reviewer_failure_keeps_candidates(monkeypatch):
    engine_calls, captured = _patch_common(monkeypatch)
    payload = create_optimization_workflow(
        MagicMock(),
        _ctx(),
        "alert-42",
        provider=FakeOptProvider(review_error=LLMProviderError("review down")),
    )
    assert payload["workflowStatus"] == WorkflowStatus.REVIEW_UNAVAILABLE.value
    assert [row["candidateId"] for row in payload["candidates"]] == ["c-1", "c-2"]
    assert payload["displayedCandidateIds"] == ["c-2"]
    assert REVIEW_UNAVAILABLE_COPY in payload["explanation"]["why"]
    assert len(engine_calls) == 1
    assert captured["snapshot"]["workflow"]["reviewStatus"] is None


def test_workflow_reoptimize_runs_engines_twice_then_stops(monkeypatch):
    engine_calls, captured = _patch_common(monkeypatch)
    provider = FakeOptProvider(
        reviews=[
            OptimizationReview(status=ReviewStatus.REOPTIMIZE, reoptimization_reason="add mechanical"),
            OptimizationReview(status=ReviewStatus.REOPTIMIZE, reoptimization_reason="again"),
        ]
    )
    payload = create_optimization_workflow(MagicMock(), _ctx(), "alert-42", provider=provider)
    assert len(engine_calls) == MAX_OPTIMIZATION_PASSES == 2
    assert len(provider.review_calls) == 2
    assert captured["snapshot"]["workflow"]["reoptimizationOccurred"] is True
    assert captured["snapshot"]["workflow"]["optimizationPassCount"] == 2
    assert payload["displayedCandidateIds"] == ["c-2"]


def test_workflow_no_change_when_baseline_is_best(monkeypatch):
    current_best = [
        {**_candidates()[0], "score": 4.0, "waitMinutes": 0.0},
        {**_candidates()[1], "score": 9.0, "waitMinutes": 10.0, "candidateId": "c-2"},
    ]
    _patch_common(monkeypatch, engines=current_best)
    payload = create_optimization_workflow(MagicMock(), _ctx(), "alert-42", provider=FakeOptProvider())
    assert payload["workflowStatus"] == WorkflowStatus.NO_CHANGE_RECOMMENDED.value
    assert payload["displayedCandidateIds"] == []
    assert payload["explanation"]["why"] == NO_CHANGE_OPERATOR_COPY


def test_workflow_planner_payload_has_no_numeric_facts(monkeypatch):
    _patch_common(monkeypatch)
    provider = FakeOptProvider()
    create_optimization_workflow(MagicMock(), _ctx(), "alert-42", provider=provider)
    assert provider.plan_calls
    assert payload_contains_forbidden_numeric_facts(provider.plan_calls[0]) is False


def test_confirmed_loader_rca_from_investigation_still_hard_excludes(monkeypatch):
    from app.db.enums import EquipmentType

    _engine_calls, captured = _patch_common(monkeypatch)
    row = SimpleNamespace(
        conclusion={"diagnosis_status": "CONFIRMED", "reliable_root_cause": True, "supported_hypothesis_ids": ["h-1"]},
        recommendation={"target_equipment_id": 10},
        equipment_id=10,
    )
    monkeypatch.setattr("app.ai.optimization.workflow.find_investigations", lambda *_a, **_k: [row])

    def trusted(*_a, **_k):
        payload = _trusted()
        payload.loaders[0].type = EquipmentType.LOADER
        return payload

    monkeypatch.setattr("app.ai.optimization.workflow.build_trusted_optimization_input", trusted)
    payload = create_optimization_workflow(MagicMock(), _ctx(), "alert-42", provider=FakeOptProvider())
    assert captured["snapshot"]["workflow"]["rcaGate"]["hardExcludeLoaderIds"] == [10]
    assert all(item["loaderId"] != 10 for item in payload["candidates"])


def test_workflow_records_stage_timings(monkeypatch):
    _engine_calls, captured = _patch_common(monkeypatch)
    create_optimization_workflow(MagicMock(), _ctx(), "alert-42", provider=FakeOptProvider())
    timings = captured["snapshot"]["workflow"]["timings"]
    assert "weather_ms" in timings
    assert "trusted_input_ms" in timings
    assert "planner_ms" in timings
    assert "engine_pass_1_ms" in timings
    assert "reviewer_pass_1_ms" in timings
    assert "sk-" not in str(captured["snapshot"])


def test_reviewer_skipped_when_remaining_budget_below_timeout(monkeypatch):
    _patch_common(monkeypatch)
    provider = FakeOptProvider(remaining_seconds=30, timeout_seconds=15, plan_cost=20)
    payload = create_optimization_workflow(MagicMock(), _ctx(), "alert-42", provider=provider)
    assert payload["workflowStatus"] == WorkflowStatus.REVIEW_UNAVAILABLE.value
    assert provider.review_calls == []
    assert [row["candidateId"] for row in payload["candidates"]] == ["c-1", "c-2"]


def test_second_pass_skipped_when_shared_budget_exhausted(monkeypatch):
    engine_calls, _captured = _patch_common(monkeypatch)
    provider = FakeOptProvider(
        reviews=[OptimizationReview(status=ReviewStatus.REOPTIMIZE, reoptimization_reason="retry")],
        remaining_seconds=15,
        timeout_seconds=15,
        review_cost=15,
    )
    payload = create_optimization_workflow(MagicMock(), _ctx(), "alert-42", provider=provider)
    assert len(engine_calls) == 1
    assert len(provider.review_calls) == 1
    assert payload["workflowStatus"] == WorkflowStatus.REVIEW_UNAVAILABLE.value


def test_format_optimization_timeline_has_no_secrets():
    from app.ai.optimization.workflow import format_optimization_timeline

    text = format_optimization_timeline({
        "workflow": {
            "workflowStatus": "ORCHESTRATED",
            "optimizationPassCount": 1,
            "planner": {"provider": "groq", "fallbackOccurred": False},
            "reviewer": {"provider": "groq", "failed": False},
            "timings": {
                "optimization_total_ms": 9100,
                "planner_ms": 4200,
                "reviewer_pass_1_ms": 3800,
                "engine_pass_1_ms": 20,
            },
        }
    })
    assert "planner_ms=4200" in text
    assert "sk-" not in text
    assert "gsk_" not in text
