from types import SimpleNamespace

from app.mappers.dto import road_to_dto
from app.services.operational.roads import ROAD_STATUSES, STATUS_REASONS, _validate_reason, _validate_status
from simulator.seed import ROAD_SPECS, ZONE_SPECS
from app.services.operational.road_network import can_reach, routable_edges


def test_road_dto_keeps_nulls_and_status():
    road = SimpleNamespace(
        road_id=9,
        code="R-05",
        name="R-05 Banc A — Parking",
        from_zone_id=1,
        to_zone_id=2,
        distance_km=None,
        speed_limit_kmh=None,
        status="RESTRICTED",
        description=None,
        status_reason="MAINTENANCE",
        status_note=None,
        geometry=None,
    )
    dto = road_to_dto(road, {1: "BANC_A", 2: "PARKING"}, "MP-SIM-01")
    assert dto["id"] == "R-05"
    assert dto["databaseId"] == 9
    assert dto["status"] == "RESTRICTED"
    assert dto["distanceKm"] is None
    assert dto["speedLimitKmh"] is None
    assert dto["description"] is None
    assert dto["statusReason"] == "MAINTENANCE"
    assert dto["statusNote"] is None


def test_status_validation_accepts_operator_values_only():
    assert _validate_status("closed") == "CLOSED"
    assert ROAD_STATUSES == {"OPEN", "CLOSED", "RESTRICTED"}
    assert "BLASTING" in STATUS_REASONS
    assert _validate_reason("OPEN", "BLASTING") is None
    assert _validate_reason("CLOSED", "BLASTING") == "BLASTING"


def test_seed_layout_has_operational_zones_and_alternate_crusher_path():
    zone_codes = {row[0] for row in ZONE_SPECS}
    zone_types = {row[0]: row[2].name for row in ZONE_SPECS}
    assert {"BANC_A", "BANC_B", "CRUSHER", "DUMP_N", "DUMP_S", "FUEL", "WORKSHOP", "PARKING", "BLAST_PAD"} <= zone_codes
    assert zone_types["BLAST_PAD"] == "RESTRICTED_AREA"
    assert all(len(row[6]) > 20 for row in ZONE_SPECS)

    roads = [
        {
            "id": spec[2],
            "fromZoneId": spec[0],
            "toZoneId": spec[1],
            "status": "OPEN",
        }
        for spec in ROAD_SPECS
    ]
    codes = {spec[2] for spec in ROAD_SPECS}
    assert "RD-BA-CR" in codes
    assert "R-05" in codes
    assert "R-06" in codes
    closed_primary = [{**r, "status": "CLOSED"} if r["id"] == "RD-BA-CR" else r for r in roads]
    assert can_reach("BANC_A", "CRUSHER", closed_primary)
    assert {e["id"] for e in routable_edges(closed_primary)} >= {"R-05", "R-06"}


def test_seed_does_not_treat_description_as_zone_type():
    for code, _name, ztype, _xy, _cap, _color, description in ZONE_SPECS:
        assert ztype.name != description
        assert "LOADING" in ztype.name or "DUMP" in ztype.name or "CRUSHER" in ztype.name or "FUEL" in ztype.name or "MAINTENANCE" in ztype.name or "PARKING" in ztype.name or "RESTRICTED" in ztype.name
