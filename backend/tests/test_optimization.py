from pathlib import Path
from types import SimpleNamespace

from app.optimization.eligibility import NOT_APPLICABLE, OPTIMIZABLE, eligibility_for_alert
from app.optimization.solver import (
    DEFAULT_WEIGHTS,
    generate_candidates,
    score_candidate,
)


def test_eligibility_matrix():
    assert eligibility_for_alert(SimpleNamespace(alert_type="CONGESTION_RISK", metadata_={})) == OPTIMIZABLE
    assert eligibility_for_alert(SimpleNamespace(alert_type="PRODUCTION_DEVIATION", metadata_={})) == OPTIMIZABLE
    assert eligibility_for_alert(
        SimpleNamespace(alert_type="EQUIPMENT_ANOMALY", metadata_={"monitoring": {"detector_id": "prolonged-idle-wait"}})
    ) == OPTIMIZABLE
    assert eligibility_for_alert(
        SimpleNamespace(alert_type="EQUIPMENT_ANOMALY", metadata_={"monitoring": {"detectorId": "abnormal-cycle-duration"}})
    ) == OPTIMIZABLE
    assert eligibility_for_alert(
        SimpleNamespace(
            alert_type="OPERATIONAL_EVENT",
            metadata_={"monitoring": {"detectorId": "prolonged-idle-wait"}},
        )
    ) == OPTIMIZABLE
    assert eligibility_for_alert(SimpleNamespace(alert_type="EQUIPMENT_ANOMALY", metadata_={})) == NOT_APPLICABLE
    assert eligibility_for_alert(SimpleNamespace(alert_type="PREDICTED_MECHANICAL_FAILURE_RISK", metadata_={})) == NOT_APPLICABLE
    assert eligibility_for_alert(SimpleNamespace(alert_type="EQUIP_FAILURE", metadata_={})) == NOT_APPLICABLE


def test_score_does_not_treat_null_as_zero():
    assert score_candidate(None, 4.0, DEFAULT_WEIGHTS) is None
    assert score_candidate(3.0, None, DEFAULT_WEIGHTS) is None
    assert score_candidate(3.0, 4.0, DEFAULT_WEIGHTS) == 7.0


def test_incomplete_metrics_rank_after_scored_candidates():
    roads = [
        {
            "id": "R-1",
            "fromZoneId": "L1",
            "toZoneId": "D1",
            "status": "OPEN",
            "distanceKm": 2.0,
            "speedLimitKmh": 30.0,
        },
        {
            "id": "R-2",
            "fromZoneId": "L2",
            "toZoneId": "D1",
            "status": "OPEN",
            "distanceKm": None,
            "speedLimitKmh": 30.0,
        },
    ]
    truck = SimpleNamespace(equipment_id=1, code="TRK-1")
    assignment = SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3, assignment_id=9)
    loaders = [
        SimpleNamespace(equipment_id=10, code="LD-1", active=True, current_state=None, current_zone_id=1),
        SimpleNamespace(equipment_id=11, code="LD-2", active=True, current_state=None, current_zone_id=2),
    ]
    from app.db.enums import EquipmentState

    loaders[0].current_state = EquipmentState.LOADING
    loaders[1].current_state = EquipmentState.LOADING
    loading = {
        "loaders": [
            {"loaderId": 10, "waitingTruckCount": 1, "waitingTrucks": [{"waitingMinutes": 8.0}]},
            {"loaderId": 11, "waitingTruckCount": 0, "waitingTrucks": []},
        ]
    }
    candidates = generate_candidates(
        truck=truck,
        assignment=assignment,
        loaders=loaders,
        roads=roads,
        zone_codes={1: "L1", 2: "L2", 3: "D1"},
        loading=loading,
        origin_code=None,
        dest_code="D1",
    )
    assert candidates
    scored = [row for row in candidates if row["score"] is not None]
    unscored = [row for row in candidates if row["score"] is None]
    assert scored
    assert unscored
    assert scored[0]["rank"] < unscored[0]["rank"]


def test_closed_roads_are_not_candidates():
    roads = [
        {
            "id": "R-X",
            "fromZoneId": "L1",
            "toZoneId": "D1",
            "status": "CLOSED",
            "distanceKm": 1.0,
            "speedLimitKmh": 20.0,
        }
    ]
    from app.db.enums import EquipmentState

    loader = SimpleNamespace(equipment_id=10, code="LD-1", active=True, current_state=EquipmentState.LOADING)
    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=2),
        loaders=[loader],
        roads=roads,
        zone_codes={1: "L1", 2: "D1"},
        loading={"loaders": [{"loaderId": 10, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="L1",
        dest_code="D1",
    )
    assert candidates == []


def test_optimizer_package_does_not_import_llm_simulator_or_road_mutations():
    root = Path("app/optimization")
    forbidden = (
        "simulator",
        "app.services.operational.roads",
        "app.ai.llm",
        "app.ai.graph",
        "app.ai.nodes",
    )
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
            assert f"from {name} " not in text


def _loader_fixture():
    from app.db.enums import EquipmentState

    return SimpleNamespace(
        equipment_id=10,
        code="LD-1",
        active=True,
        current_state=EquipmentState.LOADING,
        current_zone_id=1,
    )


def test_path_constraint_notes_do_not_leak_and_duplicate_paths_are_dropped(monkeypatch):
    from app.optimization import solver as solver_mod

    monkeypatch.setattr(solver_mod, "can_reach", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        solver_mod,
        "candidate_paths",
        lambda *_args, **_kwargs: [
            {"roadIds": ["R-1"], "totalDistanceKm": 1.0, "estimatedTravelMinutes": 2.0, "containsRestrictedRoad": True},
            {"roadIds": ["R-2"], "totalDistanceKm": 2.0, "estimatedTravelMinutes": 4.0, "containsRestrictedRoad": False},
            {"roadIds": ["R-1"], "totalDistanceKm": 1.0, "estimatedTravelMinutes": 2.0, "containsRestrictedRoad": True},
        ],
    )
    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=2),
        loaders=[_loader_fixture()],
        roads=[{"id": "R-1", "fromZoneId": "L1", "toZoneId": "D1", "status": "OPEN", "distanceKm": 1.0, "speedLimitKmh": 20.0}],
        zone_codes={1: "L1", 2: "D1"},
        loading={"loaders": [{"loaderId": 10, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="L1",
        dest_code="D1",
    )
    assert [row["roadIds"] for row in candidates] == [["R-1"], ["R-2"]] or {tuple(row["roadIds"]) for row in candidates} == {("R-1",), ("R-2",)}
    by_road = {tuple(row["roadIds"]): row for row in candidates}
    assert "RESTRICTED" in by_road[("R-1",)]["constraintNotes"]
    assert "RESTRICTED" not in by_road[("R-2",)]["constraintNotes"]


def test_generate_candidates_is_deterministic():
    from app.db.enums import EquipmentState

    kwargs = dict(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=2),
        loaders=[
            SimpleNamespace(equipment_id=10, code="LD-1", active=True, current_state=EquipmentState.LOADING, current_zone_id=1),
        ],
        roads=[
            {"id": "R-1", "fromZoneId": "L1", "toZoneId": "D1", "status": "OPEN", "distanceKm": 2.0, "speedLimitKmh": 30.0},
        ],
        zone_codes={1: "L1", 2: "D1"},
        loading={"loaders": [{"loaderId": 10, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="L1",
        dest_code="D1",
    )
    first = generate_candidates(**kwargs)
    second = generate_candidates(**kwargs)
    assert [row["candidateId"] for row in first] == [row["candidateId"] for row in second]
    assert [row["score"] for row in first] == [row["score"] for row in second]

