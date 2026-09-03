from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.db.enums import EquipmentState, EquipmentType
from app.optimization.location import (
    LOCATION_HOME,
    LOCATION_POSITION,
    LOCATION_UNKNOWN,
    resolve_loader_location,
    zone_runtime_capacity,
)
from app.optimization.solver import generate_candidates


NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
STALE = 120.0


def test_fresh_position_wins_over_home_zone():
    code, source = resolve_loader_location(
        position_zone_id=2,
        position_ts=NOW - timedelta(seconds=30),
        home_zone_id=1,
        now=NOW,
        stale_seconds=STALE,
        zone_codes={1: "BANC_A", 2: "BANC_B"},
    )
    assert code == "BANC_B"
    assert source == LOCATION_POSITION


def test_stale_position_falls_back_to_home_zone():
    code, source = resolve_loader_location(
        position_zone_id=2,
        position_ts=NOW - timedelta(seconds=STALE + 1),
        home_zone_id=1,
        now=NOW,
        stale_seconds=STALE,
        zone_codes={1: "BANC_A", 2: "BANC_B"},
    )
    assert code == "BANC_A"
    assert source == LOCATION_HOME


def test_missing_position_and_home_is_unknown():
    code, source = resolve_loader_location(
        position_zone_id=None,
        position_ts=None,
        home_zone_id=None,
        now=NOW,
        stale_seconds=STALE,
        zone_codes={1: "BANC_A"},
    )
    assert code is None
    assert source == LOCATION_UNKNOWN


def test_unknown_loader_location_does_not_use_truck_origin():
    loader = SimpleNamespace(
        equipment_id=11,
        code="LDR-001",
        active=True,
        current_state=EquipmentState.LOADING,
    )
    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[loader],
        roads=[
            {
                "id": "R-1",
                "fromZoneId": "BANC_A",
                "toZoneId": "DUMP_N",
                "status": "OPEN",
                "distanceKm": 2.0,
                "speedLimitKmh": 30.0,
            }
        ],
        zone_codes={1: "BANC_A", 3: "DUMP_N"},
        loading={"loaders": [{"loaderId": 11, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="BANC_A",
        dest_code="DUMP_N",
        loader_zones={},
    )
    assert candidates == []


def test_known_home_zone_does_not_teleport_to_subject_truck_bench():
    loader = SimpleNamespace(
        equipment_id=11,
        code="LDR-001",
        active=True,
        current_state=EquipmentState.LOADING,
    )
    candidates = generate_candidates(
        truck=SimpleNamespace(equipment_id=1, code="TRK-1"),
        assignment=SimpleNamespace(loader_id=10, origin_zone_id=1, destination_zone_id=3),
        loaders=[loader],
        roads=[
            {
                "id": "R-B",
                "fromZoneId": "BANC_B",
                "toZoneId": "DUMP_N",
                "status": "OPEN",
                "distanceKm": 2.0,
                "speedLimitKmh": 30.0,
            }
        ],
        zone_codes={1: "BANC_A", 2: "BANC_B", 3: "DUMP_N"},
        loading={"loaders": [{"loaderId": 11, "waitingTruckCount": 0, "waitingTrucks": []}]},
        origin_code="BANC_A",
        dest_code="DUMP_N",
        loader_zones={11: "BANC_B"},
    )
    assert candidates
    assert {row["originZoneCode"] for row in candidates} == {"BANC_B"}


def test_mechanical_risk_ids_exclude_haul_trucks():
    from app.optimization.inputs import filter_mechanical_risk_loader_ids

    truck = SimpleNamespace(equipment_id=7, type=EquipmentType.HAUL_TRUCK)
    shovel = SimpleNamespace(equipment_id=21, type=EquipmentType.EXCAVATOR)
    loader = SimpleNamespace(equipment_id=24, type=EquipmentType.LOADER)
    assert filter_mechanical_risk_loader_ids({7, 21, 99}, [truck, shovel, loader]) == {21}


def test_zero_zone_capacity_is_not_treated_as_missing():
    assert zone_runtime_capacity(None) == 3
    assert zone_runtime_capacity(0) == 0
    assert zone_runtime_capacity(4) == 4
