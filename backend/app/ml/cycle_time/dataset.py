"""Read-only cycle snapshot for cycle-time training and inference.

Does not add ML targets to operational services. ACTIVE cycles are loaded for
point-in-time queue reconstruction and history, but never become training rows
with duration 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.db.models import Cycle, Equipment, HaulRoad, Zone
from app.db.models.telemetry import EquipmentState as EquipmentStateRow

DURATION_MISMATCH_SEC = 5.0


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


@dataclass(frozen=True)
class CycleRecord:
    cycle_id: int
    truck_id: int | None
    loader_id: int | None
    origin_zone_id: int | None
    destination_zone_id: int | None
    started_at: datetime | None
    completed_at: datetime | None
    total_duration_sec: int | None
    status: str
    payload_t: float | None = None
    distance_km: float | None = None


@dataclass(frozen=True)
class EquipmentInfo:
    equipment_id: int
    code: str
    model: str | None
    capacity_t: float | None


@dataclass(frozen=True)
class StateInterval:
    equipment_id: int
    state: str
    start_time: datetime
    end_time: datetime | None


@dataclass
class CycleSnapshot:
    cycles: list[CycleRecord]
    equipment: dict[int, EquipmentInfo]
    zones: dict[int, str]
    road_distance_km: dict[tuple[int, int], float]
    waiting_states: list[StateInterval]
    excluded: dict[str, int] = field(default_factory=dict)


def cycle_from_orm(row: Cycle) -> CycleRecord:
    payload = float(row.payload_t) if row.payload_t is not None else None
    distance = float(row.distance_km) if row.distance_km is not None else None
    return CycleRecord(
        cycle_id=int(row.cycle_id),
        truck_id=int(row.truck_id) if row.truck_id is not None else None,
        loader_id=int(row.loader_id) if row.loader_id is not None else None,
        origin_zone_id=int(row.origin_zone_id) if row.origin_zone_id is not None else None,
        destination_zone_id=int(row.destination_zone_id) if row.destination_zone_id is not None else None,
        started_at=_aware(row.started_at),
        completed_at=_aware(row.completed_at),
        total_duration_sec=int(row.total_duration_sec) if row.total_duration_sec is not None else None,
        status=str(row.status),
        payload_t=payload,
        distance_km=distance,
    )


def load_snapshot(session: Session, *, site_id: int | None = None) -> CycleSnapshot:
    cycles_query = select(Cycle)
    equipment_query = select(Equipment)
    zones_query = select(Zone)
    roads_query = select(HaulRoad)
    waiting_query = select(EquipmentStateRow).where(EquipmentStateRow.state == EquipmentState.WAITING_LOADING)
    if site_id is not None:
        cycles_query = cycles_query.join(Equipment, Cycle.truck_id == Equipment.equipment_id).where(
            Equipment.site_id == site_id
        )
        equipment_query = equipment_query.where(Equipment.site_id == site_id)
        zones_query = zones_query.where(Zone.site_id == site_id)
        roads_query = roads_query.where(HaulRoad.site_id == site_id)
        waiting_query = waiting_query.join(
            Equipment, EquipmentStateRow.equipment_id == Equipment.equipment_id
        ).where(Equipment.site_id == site_id)
    cycles = [cycle_from_orm(row) for row in session.scalars(cycles_query).all()]
    equipment = {
        int(row.equipment_id): EquipmentInfo(
            equipment_id=int(row.equipment_id),
            code=row.code,
            model=row.model,
            capacity_t=float(row.capacity_t) if row.capacity_t is not None else None,
        )
        for row in session.scalars(equipment_query).all()
    }
    zones = {int(row.zone_id): row.code for row in session.scalars(zones_query).all()}
    roads: dict[tuple[int, int], float] = {}
    for row in session.scalars(roads_query).all():
        if row.from_zone_id is None or row.to_zone_id is None or row.distance_km is None:
            continue
        roads[(int(row.from_zone_id), int(row.to_zone_id))] = float(row.distance_km)
    waiting = [
        StateInterval(
            equipment_id=int(row.equipment_id),
            state=row.state.value if hasattr(row.state, "value") else str(row.state),
            start_time=_aware(row.start_time) or row.start_time,
            end_time=_aware(row.end_time),
        )
        for row in session.scalars(waiting_query).all()
    ]
    return CycleSnapshot(
        cycles=cycles,
        equipment=equipment,
        zones=zones,
        road_distance_km=roads,
        waiting_states=waiting,
    )


def timestamp_duration_sec(started_at: datetime, completed_at: datetime) -> float:
    return (completed_at - started_at).total_seconds()


def training_target_minutes(cycle: CycleRecord) -> float | None:
    if cycle.total_duration_sec is None or cycle.total_duration_sec <= 0:
        return None
    return cycle.total_duration_sec / 60.0


def is_valid_training_cycle(cycle: CycleRecord) -> tuple[bool, str | None]:
    if cycle.status != "COMPLETED":
        return False, "not_completed"
    if cycle.truck_id is None:
        return False, "missing_truck_id"
    if cycle.started_at is None or cycle.completed_at is None:
        return False, "missing_timestamps"
    if cycle.total_duration_sec is None:
        return False, "missing_target"
    if cycle.total_duration_sec <= 0:
        return False, "non_positive_duration"
    delta = abs(cycle.total_duration_sec - timestamp_duration_sec(cycle.started_at, cycle.completed_at))
    if delta > DURATION_MISMATCH_SEC:
        return False, "duration_mismatch"
    return True, None


def select_training_cycles(cycles: list[CycleRecord]) -> tuple[list[CycleRecord], dict[str, int]]:
    kept: list[CycleRecord] = []
    excluded = {
        "not_completed": 0,
        "missing_truck_id": 0,
        "missing_timestamps": 0,
        "missing_target": 0,
        "non_positive_duration": 0,
        "duration_mismatch": 0,
    }
    for cycle in cycles:
        ok, reason = is_valid_training_cycle(cycle)
        if ok:
            kept.append(cycle)
        elif reason:
            excluded[reason] = excluded.get(reason, 0) + 1
    kept.sort(key=lambda row: (row.started_at or datetime.min.replace(tzinfo=timezone.utc), row.cycle_id))
    return kept, excluded


def snapshot_summary(snapshot: CycleSnapshot) -> dict[str, Any]:
    kept, excluded = select_training_cycles(snapshot.cycles)
    return {
        "cycles_loaded": len(snapshot.cycles),
        "training_rows": len(kept),
        "excluded": excluded,
        "equipment": len(snapshot.equipment),
        "zones": len(snapshot.zones),
        "roads": len(snapshot.road_distance_km),
        "waiting_state_intervals": len(snapshot.waiting_states),
    }
