"""Data-driven haul assignment from PostgreSQL topology.

New loading benches, roads, or loading equipment are discovered at simulator
**restart**. A running process does not hot-reload catalog rows. Capacity is an
occupancy/pressure signal, never a hard cap on how many trucks may be assigned.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from simulator.world import stable_seed

LOADING_BENCH = "LOADING_BENCH"
HAUL_DEST_TYPES = frozenset({"DUMP_AREA", "CRUSHER"})


@dataclass(frozen=True)
class FeasibleSlot:
    loader_code: str
    loader_id: int
    bench_code: str
    dest_code: str
    occupancy: int


@dataclass(frozen=True)
class FleetAssignment:
    equipment_id: int
    truck_code: str
    loader_code: str
    loader_id: int
    bench_code: str
    dest_code: str


def _dump_destinations(
    bench: str,
    roads: list[tuple[str, str]],
    zone_types: dict[str, str],
) -> list[str]:
    dests: list[str] = []
    seen: set[str] = set()
    for from_code, to_code in roads:
        neighbor = None
        if from_code == bench:
            neighbor = to_code
        elif to_code == bench:
            neighbor = from_code
        if neighbor is None or neighbor in seen:
            continue
        if zone_types.get(neighbor) in HAUL_DEST_TYPES:
            seen.add(neighbor)
            dests.append(neighbor)
    return dests


def discover_feasible_slots(
    *,
    zone_types: dict[str, str],
    zone_capacity: dict[str, int],
    zone_status: dict[str, str],
    loaders: list[tuple[str, int, str | None]],
    roads: list[tuple[str, str]],
) -> list[FeasibleSlot]:
    """Slots are (loader @ LOADING_BENCH with a road to a dump/crusher)."""
    slots: list[FeasibleSlot] = []
    for loader_code, loader_id, bench in loaders:
        if not bench:
            continue
        if zone_types.get(bench) != LOADING_BENCH:
            continue
        if str(zone_status.get(bench, "ACTIVE")).upper() != "ACTIVE":
            continue
        dests = _dump_destinations(bench, roads, zone_types)
        occupancy = int(zone_capacity.get(bench, 3) or 0)
        for dest in dests:
            slots.append(
                FeasibleSlot(
                    loader_code=loader_code,
                    loader_id=loader_id,
                    bench_code=bench,
                    dest_code=dest,
                    occupancy=occupancy,
                )
            )
    return slots


def _pressure_weight(assigned_count: int, occupancy: int) -> float:
    pad = max(1, occupancy)
    return 1.0 / (1.0 + assigned_count + (assigned_count / pad))


def assign_fleet(
    trucks: list[tuple[int, str]],
    slots: list[FeasibleSlot],
    seed: int,
) -> list[FleetAssignment]:
    """Assign every truck to a feasible slot. Occupancy is pressure, not a cap."""
    if not slots:
        return []
    by_loader: dict[str, list[FeasibleSlot]] = defaultdict(list)
    for slot in slots:
        by_loader[slot.loader_code].append(slot)
    loader_order = sorted(by_loader)
    assigned_counts: dict[str, int] = {code: 0 for code in loader_order}
    results: list[FleetAssignment] = []
    for equipment_id, truck_code in trucks:
        rng = random.Random(stable_seed(seed, equipment_id, truck_code))
        weights = [
            _pressure_weight(assigned_counts[code], by_loader[code][0].occupancy)
            for code in loader_order
        ]
        loader_code = rng.choices(loader_order, weights=weights, k=1)[0]
        dest_slot = rng.choice(by_loader[loader_code])
        assigned_counts[loader_code] += 1
        results.append(
            FleetAssignment(
                equipment_id=equipment_id,
                truck_code=truck_code,
                loader_code=loader_code,
                loader_id=dest_slot.loader_id,
                bench_code=dest_slot.bench_code,
                dest_code=dest_slot.dest_code,
            )
        )
    return results
