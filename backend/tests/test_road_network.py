from app.services.operational.road_network import (
    MAX_CANDIDATE_PATHS,
    build_route_context,
    can_reach,
    candidate_paths,
    road_fact,
    road_status,
    routable_edges,
    travel_minutes,
)


def _road(**kwargs):
    base = {
        "id": "R-03",
        "name": "R-03 Banc A — Concasseur",
        "fromZoneId": "BANC_A",
        "toZoneId": "CRUSHER",
        "status": "OPEN",
        "distanceKm": 4.2,
        "speedLimitKmh": 35,
        "description": None,
        "statusReason": None,
        "statusNote": None,
    }
    base.update(kwargs)
    return base


def test_missing_and_invalid_status_are_unknown_not_open():
    assert road_status({}) == "UNKNOWN"
    assert road_status({"status": None}) == "UNKNOWN"
    assert road_status({"status": "WEIRD"}) == "UNKNOWN"
    assert road_status({"status": "CLOSED"}) == "CLOSED"
    assert road_status({"status": "OPEN"}) == "OPEN"


def test_routable_edges_exclude_closed_unknown_missing_and_invalid():
    edges = routable_edges(
        [
            _road(id="R-03", status="CLOSED"),
            _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", status="OPEN"),
            _road(id="R-06", fromZoneId="PARKING", toZoneId="CRUSHER", status="RESTRICTED"),
            _road(id="R-x", status=None),
            {"id": "R-n", "fromZoneId": "BANC_A", "toZoneId": "CRUSHER"},
            _road(id="R-bad", status="OPENISH"),
        ]
    )
    assert {e["id"] for e in edges} == {"R-05", "R-06"}
    assert next(e["status"] for e in edges if e["id"] == "R-06") == "RESTRICTED"


def test_can_reach_uses_alternate_path_when_primary_is_closed():
    primary = _road(id="R-03", status="CLOSED")
    alt = [
        _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", distanceKm=3.4, speedLimitKmh=38),
        _road(id="R-06", fromZoneId="PARKING", toZoneId="CRUSHER", distanceKm=2.8, speedLimitKmh=35),
    ]
    assert can_reach("BANC_A", "CRUSHER", [primary]) is False
    assert can_reach("BANC_A", "CRUSHER", [primary, *alt]) is True
    assert can_reach("BANC_A", "DUMP_S", alt) is False
    assert can_reach("BANC_A", "CRUSHER", [_road(id="R-x", status=None)]) is False


def test_direct_open_path_and_closed_primary_forces_alternate():
    primary = _road(id="R-03", status="CLOSED", statusReason="BLASTING")
    alt = [
        _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", distanceKm=3.4, speedLimitKmh=38),
        _road(id="R-06", fromZoneId="PARKING", toZoneId="CRUSHER", distanceKm=2.8, speedLimitKmh=35),
    ]
    direct = candidate_paths("BANC_A", "CRUSHER", [_road(status="OPEN")])
    assert direct[0]["roadIds"] == ["R-03"]
    closed = candidate_paths("BANC_A", "CRUSHER", [primary, *alt])
    assert closed[0]["roadIds"] == ["R-05", "R-06"]
    assert closed[0]["totalDistanceKm"] == 6.2
    assert "R-03" not in closed[0]["roadIds"]
    assert candidate_paths("BANC_A", "DUMP_S", alt) == []


def test_restricted_segment_marks_candidate_path():
    roads = [
        _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", distanceKm=3.4, speedLimitKmh=38),
        _road(
            id="R-06",
            fromZoneId="PARKING",
            toZoneId="CRUSHER",
            status="RESTRICTED",
            statusReason="MAINTENANCE",
            distanceKm=2.8,
            speedLimitKmh=35,
        ),
    ]
    path = candidate_paths("BANC_A", "CRUSHER", roads)[0]
    assert path["containsRestrictedRoad"] is True
    assert path["restrictedRoadIds"] == ["R-06"]
    assert path["restrictionReasons"][0]["reason"] == "MAINTENANCE"


def test_travel_minutes_are_honest():
    assert travel_minutes(4.2, 35) == round((4.2 / 35) * 60, 1)
    assert travel_minutes(None, 35) is None
    assert travel_minutes(4.2, None) is None
    assert travel_minutes(4.2, 0) is None
    assert travel_minutes(4.2, -10) is None
    alt = [
        _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", distanceKm=3.4, speedLimitKmh=38),
        _road(id="R-06", fromZoneId="PARKING", toZoneId="CRUSHER", distanceKm=2.8, speedLimitKmh=35),
    ]
    path = candidate_paths("BANC_A", "CRUSHER", alt)[0]
    expected = round((travel_minutes(3.4, 38) or 0) + (travel_minutes(2.8, 35) or 0), 1)
    assert path["estimatedTravelMinutes"] == expected
    missing_speed = candidate_paths(
        "BANC_A",
        "CRUSHER",
        [
            _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", distanceKm=3.4, speedLimitKmh=None),
            _road(id="R-06", fromZoneId="PARKING", toZoneId="CRUSHER", distanceKm=2.8, speedLimitKmh=35),
        ],
    )[0]
    assert missing_speed["totalDistanceKm"] == 6.2
    assert missing_speed["estimatedTravelMinutes"] is None
    missing_distance = candidate_paths(
        "BANC_A",
        "CRUSHER",
        [
            _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", distanceKm=None, speedLimitKmh=38),
            _road(id="R-06", fromZoneId="PARKING", toZoneId="CRUSHER", distanceKm=2.8, speedLimitKmh=35),
        ],
    )[0]
    assert missing_distance["totalDistanceKm"] is None
    assert missing_distance["estimatedTravelMinutes"] is None


def test_route_context_is_bounded_and_omits_geometry():
    primary = _road(id="R-03", status="CLOSED", statusReason="BLASTING", points=[{"x": 0, "y": 0}])
    alt = [
        _road(id="R-05", fromZoneId="BANC_A", toZoneId="PARKING", distanceKm=3.4, speedLimitKmh=38),
        _road(id="R-06", fromZoneId="PARKING", toZoneId="CRUSHER", distanceKm=2.8, speedLimitKmh=35),
    ]
    payload = build_route_context([primary, *alt], origin_zone_id="BANC_A", destination_zone_id="CRUSHER")
    assert payload["reachable"] is True
    assert payload["candidatePaths"][0]["roadIds"] == ["R-05", "R-06"]
    assert len(payload["candidatePaths"]) <= MAX_CANDIDATE_PATHS
    assert any(r["id"] == "R-03" and r["eligible"] is False for r in payload["excludedRoads"])
    dumped = str(payload)
    assert "points" not in dumped
    for road in payload["relevantRoads"]:
        assert "points" not in road
        assert set(road) <= set(road_fact(primary))
