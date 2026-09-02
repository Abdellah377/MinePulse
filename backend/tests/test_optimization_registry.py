from types import SimpleNamespace

from app.optimization.compose import (
    apply_objective_policy,
    execute_selected_engines,
    finalize_recommendations,
    is_operationally_distinct,
)
from app.optimization.contracts import ConstraintCode, ObjectiveProfile, OptimizerId
from app.optimization.registry import REGISTRY, catalog_for_planner, get_spec, validate_selection
from app.optimization.solver import DEFAULT_WEIGHTS


def _row(**overrides):
    base = {
        "candidateId": "c-1",
        "loaderId": 10,
        "loaderCode": "LD-1",
        "destZoneCode": "D1",
        "roadIds": ["R-1"],
        "distanceKm": 2.0,
        "travelMinutes": 4.0,
        "waitMinutes": 8.0,
        "score": 12.0,
        "constraintNotes": [],
        "isCurrent": False,
        "rankReason": "score",
    }
    base.update(overrides)
    return base


def test_registry_exposes_only_dispatch_and_route():
    assert set(REGISTRY) == {OptimizerId.DISPATCH_LOADER, OptimizerId.ROUTE}
    catalog = catalog_for_planner()
    assert {item["optimizerId"] for item in catalog} == {"DISPATCH_LOADER", "ROUTE"}
    assert get_spec("DISPATCH_LOADER").version == "1.0.0"


def test_registry_rejects_unknown_optimizer_and_caps_two():
    ids, objectives, constraints, rejected = validate_selection(
        [OptimizerId.DISPATCH_LOADER, OptimizerId.ROUTE, OptimizerId.DISPATCH_LOADER],
        None,
        [ObjectiveProfile.REDUCE_WAITING_TIME, ObjectiveProfile.MINIMIZE_DISTANCE],
        [ConstraintCode.EXCLUDE_UNAVAILABLE_EQUIPMENT],
    )
    assert ids == [OptimizerId.DISPATCH_LOADER, OptimizerId.ROUTE]
    assert ObjectiveProfile.REDUCE_WAITING_TIME in objectives
    assert ObjectiveProfile.MINIMIZE_DISTANCE in objectives
    assert "FUEL" not in "".join(rejected)


def test_mechanical_risk_constraint_drops_flagged_loader():
    from app.optimization.constraints import apply_loader_constraints

    keep = SimpleNamespace(equipment_id=10, code="LD-1")
    drop = SimpleNamespace(equipment_id=11, code="LD-2")
    rows = apply_loader_constraints(
        [keep, drop],
        constraints=[ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK],
        mechanical_risk_loader_ids={11},
    )
    assert [row.equipment_id for row in rows] == [10]


def test_minimize_distance_sorts_without_mutating_weights():
    weights = dict(DEFAULT_WEIGHTS)
    rows = [
        _row(candidateId="far", distanceKm=9.0, score=5.0, waitMinutes=1.0, travelMinutes=1.0),
        _row(candidateId="near", distanceKm=1.0, score=8.0, waitMinutes=6.0, travelMinutes=2.0),
    ]
    ordered = apply_objective_policy(rows, [ObjectiveProfile.MINIMIZE_DISTANCE])
    assert [row["candidateId"] for row in ordered] == ["near", "far"]
    assert DEFAULT_WEIGHTS == {"w_travel": 1.0, "w_wait": 1.0}
    assert weights == DEFAULT_WEIGHTS


def test_reduce_waiting_time_sorts_by_wait_then_score():
    rows = [
        _row(candidateId="slow", waitMinutes=10.0, score=11.0, loaderId=10),
        _row(candidateId="fast", waitMinutes=1.0, score=12.0, loaderId=11, roadIds=["R-2"]),
    ]
    ordered = apply_objective_policy(rows, [ObjectiveProfile.REDUCE_WAITING_TIME])
    assert ordered[0]["candidateId"] == "fast"


def test_equivalent_only_when_operationally_distinct():
    baseline = _row(candidateId="now", isCurrent=True, score=7.0, loaderId=10, roadIds=["R-1"])
    same = _row(candidateId="clone", score=7.0, loaderId=10, roadIds=["R-1"])
    other_loader = _row(candidateId="alt", score=7.0, loaderId=11, roadIds=["R-1"])
    other_road = _row(candidateId="path", score=7.0, loaderId=10, roadIds=["R-2"])
    assert not is_operationally_distinct(same, baseline)
    assert is_operationally_distinct(other_loader, baseline)
    assert is_operationally_distinct(other_road, baseline)


def test_finalize_hides_baseline_and_caps_three_improvements():
    baseline = _row(candidateId="now", isCurrent=True, score=20.0, loaderId=10, roadIds=["R-1"])
    recs = [
        _row(candidateId=f"c-{index}", score=float(index), loaderId=20 + index, roadIds=[f"R-{index}"])
        for index in range(1, 5)
    ]
    result = finalize_recommendations([baseline, *recs])
    assert result["workflowStatus"] == "ORCHESTRATED"
    assert "now" not in result["displayedCandidateIds"]
    assert len(result["displayedCandidateIds"]) == 3
    assert result["recommendedCandidateId"] == result["displayedCandidateIds"][0]


def test_finalize_no_change_when_only_baseline_or_indistinct_ties():
    baseline = _row(candidateId="now", isCurrent=True, score=5.0, loaderId=10, roadIds=["R-1"])
    worse = _row(candidateId="worse", score=9.0, loaderId=11, roadIds=["R-2"])
    clone = _row(candidateId="clone", score=5.0, loaderId=10, roadIds=["R-1"])
    result = finalize_recommendations([baseline, worse, clone])
    assert result["workflowStatus"] == "NO_CHANGE_RECOMMENDED"
    assert result["displayedCandidateIds"] == []
    assert result["recommendedCandidateId"] == "now"
    assert result["baselineCandidateId"] == "now"


def test_finalize_equivalent_fallback_when_no_improvement():
    baseline = _row(candidateId="now", isCurrent=True, score=4.7, loaderId=10, roadIds=["R-1"], waitMinutes=0.0)
    tied = _row(candidateId="eq", score=4.7, loaderId=11, roadIds=["R-9"], waitMinutes=0.0)
    result = finalize_recommendations([baseline, tied])
    assert result["displayedCandidateIds"] == ["eq"]
    assert result["candidates"][1]["candidateRelation"] == "EQUIVALENT"
    assert result["candidates"][1]["equivalentGroupId"] == "eq-4.7"


def test_dual_engines_execute_generate_candidates_once(monkeypatch):
    calls = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return [_row(candidateId="c-1", isCurrent=True), _row(candidateId="c-2", loaderId=11, roadIds=["R-2"], score=3.0)]

    monkeypatch.setattr("app.optimization.engines.dispatch_loader.generate_candidates", fake_generate)
    trusted = {
        "truck": SimpleNamespace(equipment_id=1, code="TRK-1"),
        "assignment": SimpleNamespace(loader_id=10),
        "loaders": [SimpleNamespace(equipment_id=10, code="LD-1"), SimpleNamespace(equipment_id=11, code="LD-2")],
        "roads": [],
        "zone_codes": {},
        "loading": {"loaders": []},
        "origin_code": "L1",
        "dest_code": "D1",
        "loader_zones": {},
        "mechanical_risk_loader_ids": set(),
    }
    rows = execute_selected_engines(
        trusted=trusted,
        optimizer_ids=[OptimizerId.DISPATCH_LOADER, OptimizerId.ROUTE],
        objectives=[ObjectiveProfile.REDUCE_WAITING_TIME],
        constraints=[ConstraintCode.EXCLUDE_UNAVAILABLE_EQUIPMENT],
    )
    assert len(calls) == 1
    assert rows
    assert DEFAULT_WEIGHTS == {"w_travel": 1.0, "w_wait": 1.0}
