"""Deterministic haul-road graph selectors.

A future routing algorithm MUST use ``routable_edges`` (or an equivalent that
excludes CLOSED and UNKNOWN roads). Do not re-encode road closure inside
LangGraph prompts.
"""

from __future__ import annotations

from typing import Any, Iterable

CLOSED = "CLOSED"
RESTRICTED = "RESTRICTED"
OPEN = "OPEN"
UNKNOWN = "UNKNOWN"
ROUTABLE_STATUSES = frozenset({OPEN, RESTRICTED})


def road_status(road: Any) -> str:
    status = getattr(road, "status", None)
    if isinstance(road, dict):
        status = road.get("status", status)
    if status in (CLOSED, RESTRICTED, OPEN):
        return status
    return UNKNOWN


def is_routable_status(status: str) -> bool:
    return status in ROUTABLE_STATUSES


def _field(road: Any, *names: str) -> Any:
    if isinstance(road, dict):
        for name in names:
            if name in road:
                return road[name]
        return None
    for name in names:
        if hasattr(road, name):
            return getattr(road, name)
    return None


def routable_edges(roads: Iterable[Any]) -> list[dict[str, Any]]:
    """Directed catalog edges that a router may traverse.

    OPEN and RESTRICTED are eligible. CLOSED, UNKNOWN, missing, and invalid
    status values are never included.
    """
    edges: list[dict[str, Any]] = []
    for road in roads:
        status = road_status(road)
        if not is_routable_status(status):
            continue
        from_zone = _field(road, "fromZoneId", "from_zone_id")
        to_zone = _field(road, "toZoneId", "to_zone_id")
        if not from_zone or not to_zone:
            continue
        edges.append(
            {
                "id": _field(road, "id", "code"),
                "fromZoneId": from_zone,
                "toZoneId": to_zone,
                "status": status,
                "distanceKm": _field(road, "distanceKm", "distance_km"),
                "speedLimitKmh": _field(road, "speedLimitKmh", "speed_limit_kmh"),
            }
        )
    return edges


def can_reach(from_zone_id: str, to_zone_id: str, roads: Iterable[Any]) -> bool:
    if from_zone_id == to_zone_id:
        return True
    adjacency: dict[str, list[str]] = {}
    for edge in routable_edges(roads):
        adjacency.setdefault(edge["fromZoneId"], []).append(edge["toZoneId"])
    seen = {from_zone_id}
    queue = [from_zone_id]
    while queue:
        current = queue.pop(0)
        for nxt in adjacency.get(current, []):
            if nxt in seen:
                continue
            if nxt == to_zone_id:
                return True
            seen.add(nxt)
            queue.append(nxt)
    return False
