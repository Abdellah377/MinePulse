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
