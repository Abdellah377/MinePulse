"""Point-in-time features for cycle-time V1.

Every value must be knowable at Cycle.started_at. Historical aggregates use only
cycles with completed_at < prediction_timestamp.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Any

from app.ml.cycle_time.dataset import CycleRecord, CycleSnapshot, StateInterval, training_target_minutes

WAITING_LOADING = "WAITING_LOADING"
MISSING_CAT = "__missing__"
TRUCK_ROUTE_MIN_SAMPLES = 3
TRUCK_LAST3_MIN_SAMPLES = 3

CATEGORICAL_FEATURES = (
    "truck_code",
    "loader_code",
    "origin_code",
    "destination_code",
    "truck_model",
)
NUMERIC_FEATURES = (
    "capacity_t",
    "catalog_distance_km",
    "hour_of_day",
    "truck_prior_median",
    "truck_last3_median",
    "route_prior_median",
    "loader_prior_median",
    "truck_route_median",
    "loader_waiting_truck_count",
)
FEATURE_NAMES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

FORBIDDEN_FEATURE_NAMES = frozenset(
    {
        "total_duration_sec",
        "completed_at",
        "payload_t",
        "distance_km",
        "cycle_distance_km",
        "shift_id",
        "road_grade_pct",
        "road_quality",
        "performance_factor",
        "scenario",
        "waiting_loading_duration",
        "loading_duration",
        "same_cycle_stage_duration",
    }
)


@dataclass(frozen=True)
class FeatureRow:
    cycle_id: int
    equipment_id: int | None
    started_at: datetime | None
    target_minutes: float | None
    values: dict[str, Any]


def _cat(value: str | None) -> str:
    if value is None or value == "":
        return MISSING_CAT
    return str(value)


def _median(values: list[float], *, min_count: int = 1) -> float | None:
    if len(values) < min_count:
        return None
    return float(median(values))


def _route_key(cycle: CycleRecord) -> tuple[int, int] | None:
    if cycle.origin_zone_id is None or cycle.destination_zone_id is None:
        return None
    return (cycle.origin_zone_id, cycle.destination_zone_id)


def _truck_route_key(cycle: CycleRecord) -> tuple[int, int, int] | None:
    route = _route_key(cycle)
    if cycle.truck_id is None or route is None:
        return None
    return (cycle.truck_id, route[0], route[1])


def hour_of_day(started_at: datetime | None) -> float | None:
    if started_at is None:
        return None
    return float(started_at.hour)


def catalog_distance(cycle: CycleRecord, roads: dict[tuple[int, int], float]) -> float | None:
    route = _route_key(cycle)
    if route is None:
        return None
    return roads.get(route)


def _open_at(cycle: CycleRecord, t0: datetime) -> bool:
    if cycle.started_at is None or cycle.started_at > t0:
        return False
    if cycle.completed_at is None:
        return True
    return cycle.completed_at > t0


def _waiting_at(equipment_id: int, t0: datetime, by_equipment: dict[int, list[StateInterval]]) -> bool:
    for interval in by_equipment.get(equipment_id, ()):
        if interval.state != WAITING_LOADING:
            continue
        if interval.start_time <= t0 and (interval.end_time is None or interval.end_time > t0):
            return True
    return False


def loader_waiting_truck_count(
    cycle: CycleRecord,
    all_cycles: list[CycleRecord],
    waiting_states: list[StateInterval],
) -> float | None:
    if cycle.loader_id is None or cycle.started_at is None or cycle.truck_id is None:
        return None
    t0 = cycle.started_at
    by_equipment: dict[int, list[StateInterval]] = defaultdict(list)
    for interval in waiting_states:
        by_equipment[interval.equipment_id].append(interval)
    waiting = 0
    for other in all_cycles:
        if other.cycle_id == cycle.cycle_id or other.truck_id is None:
            continue
        if other.loader_id != cycle.loader_id or not _open_at(other, t0):
            continue
        if _waiting_at(other.truck_id, t0, by_equipment):
            waiting += 1
    return float(waiting)


def assert_no_forbidden_features(names: tuple[str, ...] | list[str]) -> None:
    overlap = FORBIDDEN_FEATURE_NAMES.intersection(names)
    if overlap:
        raise ValueError(f"Forbidden leakage features present: {sorted(overlap)}")


def build_feature_rows(
    targets: list[CycleRecord],
    snapshot: CycleSnapshot,
    *,
    include_target: bool = True,
) -> list[FeatureRow]:
    """Build PIT features for `targets` using the full snapshot for history/queue."""
    assert_no_forbidden_features(FEATURE_NAMES)
    completed = [
        cycle
        for cycle in snapshot.cycles
        if cycle.status == "COMPLETED"
        and cycle.completed_at is not None
        and cycle.total_duration_sec is not None
        and cycle.total_duration_sec > 0
    ]
    completed.sort(key=lambda row: (row.completed_at, row.cycle_id))
    ordered_targets = sorted(
        targets,
        key=lambda row: (row.started_at or datetime.min, row.cycle_id),
    )

    truck_hist: dict[int, list[float]] = defaultdict(list)
    route_hist: dict[tuple[int, int], list[float]] = defaultdict(list)
    loader_hist: dict[int, list[float]] = defaultdict(list)
    truck_route_hist: dict[tuple[int, int, int], list[float]] = defaultdict(list)
    complete_index = 0
    rows: list[FeatureRow] = []

    def ingest_completed_before(t0: datetime) -> None:
        nonlocal complete_index
        while complete_index < len(completed):
            done = completed[complete_index]
            if done.completed_at is None or done.completed_at >= t0:
                break
            minutes = training_target_minutes(done)
            complete_index += 1
            if minutes is None:
                continue
            if done.truck_id is not None:
                truck_hist[done.truck_id].append(minutes)
            route = _route_key(done)
            if route is not None:
                route_hist[route].append(minutes)
            if done.loader_id is not None:
                loader_hist[done.loader_id].append(minutes)
            truck_route = _truck_route_key(done)
            if truck_route is not None:
                truck_route_hist[truck_route].append(minutes)

    for cycle in ordered_targets:
        if cycle.started_at is not None:
            ingest_completed_before(cycle.started_at)
        truck = snapshot.equipment.get(cycle.truck_id) if cycle.truck_id is not None else None
        loader = snapshot.equipment.get(cycle.loader_id) if cycle.loader_id is not None else None
        origin = snapshot.zones.get(cycle.origin_zone_id) if cycle.origin_zone_id is not None else None
        destination = snapshot.zones.get(cycle.destination_zone_id) if cycle.destination_zone_id is not None else None
        route = _route_key(cycle)
        truck_route = _truck_route_key(cycle)
        truck_durations = truck_hist.get(cycle.truck_id, []) if cycle.truck_id is not None else []
        values = {
            "truck_code": _cat(truck.code if truck else None),
            "loader_code": _cat(loader.code if loader else None),
            "origin_code": _cat(origin),
            "destination_code": _cat(destination),
            "truck_model": _cat(truck.model if truck else None),
            "capacity_t": truck.capacity_t if truck else None,
            "catalog_distance_km": catalog_distance(cycle, snapshot.road_distance_km),
            "hour_of_day": hour_of_day(cycle.started_at),
            "truck_prior_median": _median(truck_durations),
            "truck_last3_median": _median(truck_durations[-TRUCK_LAST3_MIN_SAMPLES:], min_count=TRUCK_LAST3_MIN_SAMPLES),
            "route_prior_median": _median(route_hist[route]) if route is not None else None,
            "loader_prior_median": _median(loader_hist[cycle.loader_id]) if cycle.loader_id is not None else None,
            "truck_route_median": _median(truck_route_hist[truck_route], min_count=TRUCK_ROUTE_MIN_SAMPLES)
            if truck_route is not None
            else None,
            "loader_waiting_truck_count": loader_waiting_truck_count(cycle, snapshot.cycles, snapshot.waiting_states),
        }
        rows.append(
            FeatureRow(
                cycle_id=cycle.cycle_id,
                equipment_id=cycle.truck_id,
                started_at=cycle.started_at,
                target_minutes=training_target_minutes(cycle) if include_target else None,
                values=values,
            )
        )
    return rows


def missing_rates(rows: list[FeatureRow]) -> dict[str, float]:
    if not rows:
        return {name: 0.0 for name in FEATURE_NAMES}
    rates: dict[str, float] = {}
    n = len(rows)
    for name in FEATURE_NAMES:
        missing = 0
        for row in rows:
            value = row.values.get(name)
            if name in CATEGORICAL_FEATURES:
                if value is None or value == MISSING_CAT:
                    missing += 1
            elif value is None:
                missing += 1
        rates[name] = round(100.0 * missing / n, 1)
    return rates
