from app.services.operational.road_network import can_reach, road_status, routable_edges


def test_missing_and_invalid_status_are_unknown_not_open():
    assert road_status({}) == "UNKNOWN"
    assert road_status({"status": None}) == "UNKNOWN"
    assert road_status({"status": "WEIRD"}) == "UNKNOWN"
    assert road_status({"status": "CLOSED"}) == "CLOSED"
    assert road_status({"status": "OPEN"}) == "OPEN"


def test_routable_edges_exclude_closed_unknown_missing_and_invalid():
    edges = routable_edges(
        [
            {"id": "R-03", "fromZoneId": "BANC_A", "toZoneId": "CRUSHER", "status": "CLOSED"},
            {"id": "R-05", "fromZoneId": "BANC_A", "toZoneId": "PARKING", "status": "OPEN"},
            {"id": "R-06", "fromZoneId": "PARKING", "toZoneId": "CRUSHER", "status": "RESTRICTED"},
            {"id": "R-x", "fromZoneId": "BANC_A", "toZoneId": "CRUSHER"},
            {"id": "R-n", "fromZoneId": "BANC_A", "toZoneId": "CRUSHER", "status": None},
            {"id": "R-bad", "fromZoneId": "BANC_A", "toZoneId": "CRUSHER", "status": "OPENISH"},
        ]
    )
    assert {e["id"] for e in edges} == {"R-05", "R-06"}
    assert next(e["status"] for e in edges if e["id"] == "R-06") == "RESTRICTED"


def test_can_reach_uses_alternate_path_when_primary_is_closed():
    primary = {"id": "R-03", "fromZoneId": "BANC_A", "toZoneId": "CRUSHER", "status": "CLOSED"}
    alt = [
        {"id": "R-05", "fromZoneId": "BANC_A", "toZoneId": "PARKING", "status": "OPEN"},
        {"id": "R-06", "fromZoneId": "PARKING", "toZoneId": "CRUSHER", "status": "OPEN"},
    ]
    assert can_reach("BANC_A", "CRUSHER", [primary]) is False
    assert can_reach("BANC_A", "CRUSHER", [primary, *alt]) is True
    assert can_reach("BANC_A", "DUMP_S", alt) is False
    assert can_reach("BANC_A", "CRUSHER", [{"id": "R-x", "fromZoneId": "BANC_A", "toZoneId": "CRUSHER"}]) is False
