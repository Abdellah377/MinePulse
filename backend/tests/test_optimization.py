from pathlib import Path
from types import SimpleNamespace

from app.optimization.eligibility import NOT_APPLICABLE, OPTIMIZABLE, eligibility_for_alert
from app.optimization.solver import (
    DEFAULT_WEIGHTS,
    candidate_loader_ids,
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


def _complete_roads():
    return [
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
            "distanceKm": 3.0,
            "speedLimitKmh": 30.0,
        },
    ]


def _available_loader(equipment_id: int, code: str, zone_id: int):
    from app.db.enums import EquipmentState

    return SimpleNamespace(
        equipment_id=equipment_id,
        code=code,
        active=True,
        current_state=EquipmentState.LOADING,
        current_zone_id=zone_id,
    )


def test_complete_operational_scenario_produces_feasible_scored_candidate():
    from app.optimization.solver import FEASIBLE, dispatch_outcome

    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[_available_loader(10, "LD-1", 1), _available_loader(11, "LD-2", 2)],
        roads=_complete_roads(),
        zone_codes={1: "L1", 2: "L2", 3: "D1"},
        loading={
            "loaders": [
                {"loaderId": 10, "waitingTruckCount": 1, "waitingTrucks": [{"waitingMinutes": 8.0}]},
                {"loaderId": 11, "waitingTruckCount": 0, "waitingTrucks": []},
            ]
        },
        origin_code="L1",
        dest_code="D1",
        loader_zones={10: "L1", 11: "L2"},
    )
    scored = [row for row in candidates if row["score"] is not None]
    assert scored
    assert all(row["travelMinutes"] is not None and row["waitMinutes"] is not None for row in scored)
    outcome, missing = dispatch_outcome(
        truck=SimpleNamespace(equipment_id=1),
        dest="D1",
        candidates=candidates,
    )
    assert outcome == FEASIBLE
    assert missing is None
    empty_wait = next(row for row in candidates if row["loaderId"] == 11)
    assert empty_wait["waitMinutes"] == 0.0
    assert empty_wait["score"] is not None


def test_missing_travel_time_is_insufficient_data_with_explicit_reason():
    from app.optimization.solver import INSUFFICIENT_DATA, dispatch_outcome, explain_run

    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[_available_loader(10, "LD-1", 1)],
        roads=[
            {
                "id": "R-1",
                "fromZoneId": "L1",
                "toZoneId": "D1",
                "status": "OPEN",
                "distanceKm": 2.0,
                "speedLimitKmh": None,
            }
        ],
        zone_codes={1: "L1", 3: "D1"},
        loading={"loaders": [{"loaderId": 10, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="L1",
        dest_code="D1",
    )
    assert candidates
    assert all(row["travelMinutes"] is None for row in candidates)
    assert all(row["score"] is None for row in candidates)
    outcome, missing = dispatch_outcome(truck=SimpleNamespace(equipment_id=1), dest="D1", candidates=candidates)
    assert outcome == INSUFFICIENT_DATA
    assert missing == "Temps de trajet indisponible"
    why = explain_run(
        outcome=outcome,
        eligibility="OPTIMIZABLE",
        candidates=candidates,
        weights=DEFAULT_WEIGHTS,
        weather_status="UNAVAILABLE",
        missing_reason=missing,
    )["why"]
    assert "Temps de trajet indisponible" in why
    assert why != "Données insuffisantes pour évaluer un plan de dispatch (métrique absente ≠ 0)."


def test_missing_wait_time_is_insufficient_data_with_explicit_reason():
    from app.optimization.solver import INSUFFICIENT_DATA, dispatch_outcome, explain_run

    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[_available_loader(10, "LD-1", 1), _available_loader(11, "LD-2", 2)],
        roads=_complete_roads(),
        zone_codes={1: "L1", 2: "L2", 3: "D1"},
        loading={"loaders": []},
        origin_code="L1",
        dest_code="D1",
        loader_zones={10: "L1", 11: "L2"},
    )
    assert candidates
    assert all(row["travelMinutes"] is not None for row in candidates)
    assert all(row["waitMinutes"] is None for row in candidates)
    assert all(row["score"] is None for row in candidates)
    outcome, missing = dispatch_outcome(truck=SimpleNamespace(equipment_id=1), dest="D1", candidates=candidates)
    assert outcome == INSUFFICIENT_DATA
    assert missing == "Temps d'attente chargeur indisponible"
    why = explain_run(
        outcome=outcome,
        eligibility="OPTIMIZABLE",
        candidates=candidates,
        weights=DEFAULT_WEIGHTS,
        weather_status="UNAVAILABLE",
        missing_reason=missing,
    )["why"]
    assert "Temps d'attente chargeur indisponible" in why


def test_missing_destination_is_insufficient_data_with_explicit_reason():
    from app.optimization.solver import INSUFFICIENT_DATA, dispatch_outcome, explain_run

    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=None),
        loaders=[_available_loader(10, "LD-1", 1)],
        roads=_complete_roads(),
        zone_codes={1: "L1", 3: "D1"},
        loading={"loaders": [{"loaderId": 10, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="L1",
        dest_code=None,
    )
    assert candidates == []
    outcome, missing = dispatch_outcome(truck=SimpleNamespace(equipment_id=1), dest=None, candidates=candidates)
    assert outcome == INSUFFICIENT_DATA
    assert missing == "Destination actuelle inconnue"
    why = explain_run(
        outcome=outcome,
        eligibility="OPTIMIZABLE",
        candidates=[],
        weights=DEFAULT_WEIGHTS,
        weather_status="UNAVAILABLE",
        missing_reason=missing,
    )["why"]
    assert "Destination actuelle inconnue" in why


def test_null_metrics_are_never_coerced_to_zero():
    from app.optimization.solver import score_candidate

    assert score_candidate(None, 0.0, DEFAULT_WEIGHTS) is None
    assert score_candidate(0.0, None, DEFAULT_WEIGHTS) is None
    assert score_candidate(None, None, DEFAULT_WEIGHTS) is None
    assert score_candidate(0.0, 0.0, DEFAULT_WEIGHTS) == 0.0
    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[_available_loader(10, "LD-1", 1), _available_loader(11, "LD-2", 2)],
        roads=_complete_roads(),
        zone_codes={1: "L1", 2: "L2", 3: "D1"},
        loading={"loaders": [{"loaderId": 10, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="L1",
        dest_code="D1",
        loader_zones={10: "L1", 11: "L2"},
    )
    current = next(row for row in candidates if row["loaderId"] == 10)
    other = next(row for row in candidates if row["loaderId"] == 11)
    assert current["waitMinutes"] == 0.0
    assert current["score"] is not None
    assert other["waitMinutes"] is None
    assert other["score"] is None


def test_candidate_loader_ids_puts_current_assignment_first():
    ids = candidate_loader_ids(
        assignment=SimpleNamespace(loader_id=23),
        loaders=[
            _available_loader(21, "EXC-001", 1),
            _available_loader(23, "EXC-003", 3),
            _available_loader(22, "EXC-002", 2),
        ],
    )
    assert ids[0] == 23
    assert ids == [23, 21, 22]


def test_idle_alternative_loader_zero_wait_is_scoreable():
    from app.optimization.solver import explain_run

    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[
            _available_loader(10, "LD-1", 1),
            _available_loader(11, "LD-2", 2),
            _available_loader(12, "LD-3", 2),
        ],
        roads=_complete_roads()
        + [
            {
                "id": "R-3",
                "fromZoneId": "L2",
                "toZoneId": "D1",
                "status": "OPEN",
                "distanceKm": 2.2,
                "speedLimitKmh": 30.0,
            }
        ],
        zone_codes={1: "L1", 2: "L2", 3: "D1"},
        loading={
            "loaders": [
                {"loaderId": 10, "waitingTruckCount": 2, "waitingTrucks": [{"waitingMinutes": 10.0}]},
                {"loaderId": 11, "waitingTruckCount": 0, "waitingTrucks": []},
                {"loaderId": 12, "waitingTruckCount": 1, "waitingTrucks": [{"waitingMinutes": 2.0}]},
            ]
        },
        origin_code="L1",
        dest_code="D1",
        loader_zones={10: "L1", 11: "L2", 12: "L2"},
    )
    scored = [row for row in candidates if row["score"] is not None]
    assert len(scored) >= 3
    idle = next(row for row in candidates if row["loaderId"] == 11)
    assert idle["waitMinutes"] == 0.0
    assert idle["score"] is not None
    current = next(row for row in candidates if row["isCurrent"])
    best = min(scored, key=lambda row: row["score"])
    explanation = explain_run(
        outcome="FEASIBLE",
        eligibility="OPTIMIZABLE",
        candidates=candidates,
        weights=DEFAULT_WEIGHTS,
        weather_status="UNAVAILABLE",
    )
    assert explanation["recommendedCandidateId"] == best["candidateId"]
    assert explanation["recommendedCandidateId"] != current["candidateId"]
    assert idle["score"] < current["score"]


def test_current_plan_can_remain_recommended_when_it_has_the_lowest_score():
    from app.optimization.solver import explain_run

    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[_available_loader(10, "LD-1", 1), _available_loader(11, "LD-2", 2)],
        roads=_complete_roads(),
        zone_codes={1: "L1", 2: "L2", 3: "D1"},
        loading={
            "loaders": [
                {"loaderId": 10, "waitingTruckCount": 0, "waitingTrucks": []},
                {"loaderId": 11, "waitingTruckCount": 1, "waitingTrucks": [{"waitingMinutes": 12.0}]},
            ]
        },
        origin_code="L1",
        dest_code="D1",
        loader_zones={10: "L1", 11: "L2"},
    )
    current = next(row for row in candidates if row["isCurrent"])
    explanation = explain_run(
        outcome="FEASIBLE",
        eligibility="OPTIMIZABLE",
        candidates=candidates,
        weights=DEFAULT_WEIGHTS,
        weather_status="UNAVAILABLE",
    )
    assert explanation["recommendedCandidateId"] == current["candidateId"]
    assert "Plan actuel déjà optimal parmi les options évaluables" in explanation["why"]

