"""Deterministic haul-road graph selectors.

A future routing algorithm MUST use ``routable_edges`` (or an equivalent that
excludes CLOSED and UNKNOWN roads). Do not re-encode road closure inside
LangGraph prompts. Path search and travel time stay in this module — the LLM
only receives already-validated facts.
"""

from __future__ import annotations

from heapq import heappop, heappush
from typing import Any, Iterable

CLOSED = "CLOSED"
RESTRICTED = "RESTRICTED"
OPEN = "OPEN"
UNKNOWN = "UNKNOWN"
ROUTABLE_STATUSES = frozenset({OPEN, RESTRICTED})
MAX_CANDIDATE_PATHS = 2
MAX_RELEVANT_ROADS = 16
MAX_HOPS = 6
_MISSING_DISTANCE_WEIGHT = 1_000_000.0


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


def _as_number(value: Any, *, allow_zero: bool) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    if number < 0:
        return None
    if number == 0 and not allow_zero:
        return None
    return number


def travel_minutes(distance_km: Any, speed_kmh: Any) -> float | None:
    distance = _as_number(distance_km, allow_zero=True)
    speed = _as_number(speed_kmh, allow_zero=False)
    if distance is None or speed is None:
        return None
    return round((distance / speed) * 60.0, 1)


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
                "statusReason": _field(road, "statusReason", "status_reason"),
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


def _roads_by_id(roads: Iterable[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for road in roads:
        road_id = _field(road, "id", "code")
        if road_id:
            out[str(road_id)] = road
    return out


def path_metrics(roads: Iterable[Any], road_ids: list[str]) -> dict[str, Any]:
    by_id = _roads_by_id(roads)
    distances: list[float | None] = []
    times: list[float | None] = []
    restricted: list[str] = []
    reasons: list[dict[str, str]] = []
    uncertainty: dict[str, str] | None = None
    zone_ids: list[str] = []
    for road_id in road_ids:
        road = by_id.get(road_id)
        if road is None:
            continue
        from_zone = _field(road, "fromZoneId", "from_zone_id")
        to_zone = _field(road, "toZoneId", "to_zone_id")
        if from_zone and (not zone_ids or zone_ids[-1] != from_zone):
            zone_ids.append(str(from_zone))
        if to_zone:
            zone_ids.append(str(to_zone))
        status = road_status(road)
        if status == RESTRICTED:
            restricted.append(road_id)
            reason = _field(road, "statusReason", "status_reason")
            if reason:
                reasons.append({"roadId": road_id, "reason": str(reason)})
        distance = _as_number(_field(road, "distanceKm", "distance_km"), allow_zero=True)
        speed = _field(road, "speedLimitKmh", "speed_limit_kmh")
        distances.append(distance)
        minutes = travel_minutes(distance, speed)
        times.append(minutes)
        if minutes is None and uncertainty is None:
            uncertainty = {
                "roadId": road_id,
                "cause": "missing_distance" if distance is None else "missing_or_invalid_speed",
            }
    total_distance = None if any(item is None for item in distances) else round(sum(distances), 3)  # type: ignore[arg-type]
    total_minutes = None if any(item is None for item in times) else round(sum(times), 1)  # type: ignore[arg-type]
    return {
        "roadIds": list(road_ids),
        "zoneIds": zone_ids,
        "totalDistanceKm": total_distance,
        "estimatedTravelMinutes": total_minutes,
        "containsRestrictedRoad": bool(restricted),
        "restrictedRoadIds": restricted,
        "restrictionReasons": reasons,
        "travelTimeUncertainty": uncertainty,
    }


def _edge_weight(edge: dict[str, Any]) -> float:
    distance = _as_number(edge.get("distanceKm"), allow_zero=True)
    if distance is None:
        return _MISSING_DISTANCE_WEIGHT
    return distance


def _dijkstra(origin: str, destination: str, edges: list[dict[str, Any]]) -> list[str] | None:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["fromZoneId"], []).append(edge)
    heap: list[tuple[float, str, tuple[str, ...]]] = [(0.0, origin, ())]
    best: dict[str, float] = {origin: 0.0}
    while heap:
        cost, zone, path = heappop(heap)
        if cost > best.get(zone, _MISSING_DISTANCE_WEIGHT * 10):
            continue
        if zone == destination and path:
            return list(path)
        if len(path) >= MAX_HOPS:
            continue
        used = set(path)
        for edge in adjacency.get(zone, []):
            road_id = edge["id"]
            if road_id in used:
                continue
            nxt = edge["toZoneId"]
            nxt_cost = cost + _edge_weight(edge)
            if nxt_cost >= best.get(nxt, _MISSING_DISTANCE_WEIGHT * 10):
                continue
            best[nxt] = nxt_cost
            heappush(heap, (nxt_cost, nxt, path + (road_id,)))
    return None


def _next_simple_paths(
    origin: str,
    destination: str,
    edges: list[dict[str, Any]],
    *,
    blocked: set[str],
    limit: int,
) -> list[list[str]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if edge["id"] in blocked:
            continue
        adjacency.setdefault(edge["fromZoneId"], []).append(edge)
    found: list[list[str]] = []
    queue: list[tuple[str, tuple[str, ...], frozenset[str]]] = [(origin, (), frozenset())]
    while queue and len(found) < limit:
        zone, path, seen_zones = queue.pop(0)
        if zone == destination and path:
            found.append(list(path))
            continue
        if len(path) >= MAX_HOPS:
            continue
        for edge in adjacency.get(zone, []):
            nxt = edge["toZoneId"]
            if nxt in seen_zones or edge["id"] in path:
                continue
            queue.append((nxt, path + (edge["id"],), seen_zones | {zone}))
    return found


def candidate_paths(
    from_zone_id: str,
    to_zone_id: str,
    roads: Iterable[Any],
    *,
    max_paths: int = MAX_CANDIDATE_PATHS,
) -> list[dict[str, Any]]:
    road_list = list(roads)
    edges = routable_edges(road_list)
    if from_zone_id == to_zone_id:
        return []
    collected: list[list[str]] = []
    best = _dijkstra(from_zone_id, to_zone_id, edges)
    if best:
        collected.append(best)
        blocked = set(best)
        for alt in _next_simple_paths(from_zone_id, to_zone_id, edges, blocked=blocked, limit=4):
            if alt not in collected:
                collected.append(alt)
            if len(collected) >= max_paths + 2:
                break
    else:
        collected.extend(_next_simple_paths(from_zone_id, to_zone_id, edges, blocked=set(), limit=6))

    scored = [path_metrics(road_list, road_ids) for road_ids in collected if road_ids]
    scored.sort(
        key=lambda item: (
            0 if item["totalDistanceKm"] is not None else 1,
            item["totalDistanceKm"] if item["totalDistanceKm"] is not None else 0,
            len(item["roadIds"]),
        )
    )
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for item in scored:
        key = tuple(item["roadIds"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= max_paths:
            break
    return unique


def road_fact(road: Any) -> dict[str, Any]:
    status = road_status(road)
    return {
        "id": _field(road, "id", "code"),
        "name": _field(road, "name") or None,
        "fromZoneId": _field(road, "fromZoneId", "from_zone_id") or None,
        "toZoneId": _field(road, "toZoneId", "to_zone_id") or None,
        "status": status,
        "eligible": is_routable_status(status),
        "distanceKm": _as_number(_field(road, "distanceKm", "distance_km"), allow_zero=True),
        "speedLimitKmh": _as_number(_field(road, "speedLimitKmh", "speed_limit_kmh"), allow_zero=True),
        "description": _field(road, "description"),
        "statusReason": _field(road, "statusReason", "status_reason"),
        "statusNote": _field(road, "statusNote", "status_note"),
    }


def build_route_context(
    roads: Iterable[Any],
    *,
    origin_zone_id: str | None,
    destination_zone_id: str | None,
    max_paths: int = MAX_CANDIDATE_PATHS,
    max_relevant_roads: int = MAX_RELEVANT_ROADS,
) -> dict[str, Any]:
    road_list = list(roads)
    paths: list[dict[str, Any]] = []
    reachable: bool | None = None
    if origin_zone_id and destination_zone_id:
        reachable = can_reach(origin_zone_id, destination_zone_id, road_list)
        paths = candidate_paths(origin_zone_id, destination_zone_id, road_list, max_paths=max_paths)

    path_ids = {road_id for path in paths for road_id in path["roadIds"]}
    excluded: list[dict[str, Any]] = []
    relevant: list[dict[str, Any]] = []
    for road in road_list:
        fact = road_fact(road)
        from_zone = fact["fromZoneId"]
        to_zone = fact["toZoneId"]
        touches = from_zone in {origin_zone_id, destination_zone_id} or to_zone in {
            origin_zone_id,
            destination_zone_id,
        }
        on_path = fact["id"] in path_ids
        if not fact["eligible"] and (touches or on_path):
            excluded.append(
                {
                    "id": fact["id"],
                    "status": fact["status"],
                    "reason": fact["statusReason"],
                    "eligible": False,
                }
            )
        if on_path or touches:
            relevant.append(fact)

    return {
        "originZoneId": origin_zone_id,
        "destinationZoneId": destination_zone_id,
        "reachable": reachable,
        "excludedRoads": excluded[:8],
        "candidatePaths": paths[:max_paths],
        "relevantRoads": relevant[:max_relevant_roads],
    }
