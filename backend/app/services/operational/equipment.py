"""Bulk fleet snapshot for /equipment/live — avoids per-equipment N+1 queries."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.db.models import (
    Cycle,
    CycleStage,
    Equipment,
    EquipmentAssignment,
    EquipmentPosition,
    EquipmentState as EquipmentStateRow,
    EquipmentTelemetry,
    MaintenanceEvent,
    Operator,
)
from app.services.operational.assignments import bulk_current_assignments
from app.services.operational.context import OperationalContext
from app.services.operational.cycles import avg_cycle_minutes_bulk, shift_trip_counts

# Re-export state classification used by TD/TU (mirrors dto.py)
_UNAVAILABLE_STATES = {
    EquipmentState.STOPPED_MECHANICAL,
    EquipmentState.MAINTENANCE,
    EquipmentState.ENGINE_OFF,
    EquipmentState.NO_DATA,
    EquipmentState.PARKED,
}
_PRODUCTIVE_STATES = {
    EquipmentState.MOVING_EMPTY,
    EquipmentState.MOVING_LOADED,
    EquipmentState.WAITING_LOADING,
    EquipmentState.LOADING,
    EquipmentState.WAITING_DUMPING,
    EquipmentState.DUMPING,
    EquipmentState.REFUELING,
}
_WAIT_STATES = {EquipmentState.WAITING_LOADING, EquipmentState.WAITING_DUMPING}
_IDLE_STATES = {
    EquipmentState.STOPPED_OPERATIONAL,
    EquipmentState.STOPPED_MECHANICAL,
    EquipmentState.STOPPED_EXTERNAL,
    EquipmentState.STOPPED_UNDEFINED,
    EquipmentState.MAINTENANCE,
    EquipmentState.PARKED,
    EquipmentState.ENGINE_OFF,
}


@dataclass
class FleetBulkContext:
    positions: dict[int, EquipmentPosition] = field(default_factory=dict)
    telemetry: dict[int, EquipmentTelemetry] = field(default_factory=dict)
    trips: dict[int, int] = field(default_factory=dict)
    assignments: dict[int, EquipmentAssignment] = field(default_factory=dict)
    operators: dict[int, Operator] = field(default_factory=dict)
    open_maintenance: set[int] = field(default_factory=set)
    state_rows: dict[int, list[EquipmentStateRow]] = field(default_factory=dict)
    active_cycles: dict[int, Cycle] = field(default_factory=dict)
    cycle_stages: dict[int, list[CycleStage]] = field(default_factory=dict)
    avg_cycle_min: dict[int, float | None] = field(default_factory=dict)


def list_site_equipment(
    session: Session,
    ctx: OperationalContext,
    *,
    active_only: bool = False,
) -> list[Equipment]:
    """Canonical site-scoped equipment inventory lookup."""
    query = select(Equipment).where(Equipment.site_id == ctx.site_id)
    if active_only:
        query = query.where(Equipment.active.is_(True))
    return list(session.scalars(query.order_by(Equipment.equipment_id)).all())


def latest_positions(session: Session, site_id: int | None = None) -> dict[int, EquipmentPosition]:
    q = select(
        EquipmentPosition.equipment_id,
        func.max(EquipmentPosition.ts).label("max_ts"),
    )
    if site_id is not None:
        q = q.join(Equipment, Equipment.equipment_id == EquipmentPosition.equipment_id).where(
            Equipment.site_id == site_id
        )
    subq = q.group_by(EquipmentPosition.equipment_id).subquery()
    rows = session.execute(
        select(EquipmentPosition).join(
            subq,
            (EquipmentPosition.equipment_id == subq.c.equipment_id)
            & (EquipmentPosition.ts == subq.c.max_ts),
        )
    ).scalars().all()
    return {r.equipment_id: r for r in rows}


def latest_telemetry(session: Session, site_id: int | None = None) -> dict[int, EquipmentTelemetry]:
    q = select(
        EquipmentTelemetry.equipment_id,
        func.max(EquipmentTelemetry.ts).label("max_ts"),
    )
    if site_id is not None:
        q = q.join(Equipment, Equipment.equipment_id == EquipmentTelemetry.equipment_id).where(
            Equipment.site_id == site_id
        )
    subq = q.group_by(EquipmentTelemetry.equipment_id).subquery()
    rows = session.execute(
        select(EquipmentTelemetry).join(
            subq,
            (EquipmentTelemetry.equipment_id == subq.c.equipment_id)
            & (EquipmentTelemetry.ts == subq.c.max_ts),
        )
    ).scalars().all()
    return {r.equipment_id: r for r in rows}


def clip_interval_minutes(start, end, since, until) -> float:
    end = end or until
    if end > until:
        end = until
    if start < since:
        start = since
    return max(0.0, (end - start).total_seconds() / 60)


_clip_interval_minutes = clip_interval_minutes


def build_fleet_bulk_context(
    session: Session,
    equipment: list[Equipment],
    ctx: OperationalContext,
) -> FleetBulkContext:
    site_id = ctx.site_id
    ids = [e.equipment_id for e in equipment]
    bulk = FleetBulkContext()
    bulk.positions = latest_positions(session, site_id)
    bulk.telemetry = latest_telemetry(session, site_id)
    bulk.trips = shift_trip_counts(session, ctx)
    bulk.assignments = bulk_current_assignments(session, ids, ctx)

    op_ids = {a.operator_id for a in bulk.assignments.values() if a.operator_id}
    if op_ids:
        bulk.operators = {
            o.operator_id: o for o in session.scalars(select(Operator).where(Operator.operator_id.in_(op_ids)))
        }

    mnt_rows = session.scalars(
        select(MaintenanceEvent.equipment_id).where(
            MaintenanceEvent.equipment_id.in_(ids),
            MaintenanceEvent.status == "OPEN",
        )
    ).all()
    bulk.open_maintenance = set(mnt_rows)

    since, until = ctx.shift_window_start, ctx.sim_now
    state_rows = session.scalars(
        select(EquipmentStateRow).where(
            EquipmentStateRow.equipment_id.in_(ids),
            EquipmentStateRow.start_time < until,
            or_(EquipmentStateRow.end_time.is_(None), EquipmentStateRow.end_time > since),
        )
    ).all()
    for r in state_rows:
        bulk.state_rows.setdefault(r.equipment_id, []).append(r)

    active_cycles = session.scalars(
        select(Cycle).where(Cycle.truck_id.in_(ids), Cycle.status == "ACTIVE")
    ).all()
    for c in active_cycles:
        prev = bulk.active_cycles.get(c.truck_id)
        if prev is None or c.started_at > prev.started_at:
            bulk.active_cycles[c.truck_id] = c

    cycle_ids = [c.cycle_id for c in bulk.active_cycles.values()]
    if cycle_ids:
        stages = session.scalars(
            select(CycleStage).where(CycleStage.cycle_id.in_(cycle_ids)).order_by(CycleStage.sequence_no)
        ).all()
        for st in stages:
            bulk.cycle_stages.setdefault(st.cycle_id, []).append(st)

    bulk.avg_cycle_min = avg_cycle_minutes_bulk(session, ids, ctx)

    return bulk


def wait_idle_minutes_bulk(
    bulk: FleetBulkContext,
    equipment_id: int,
    since,
    until,
) -> tuple[float, float]:
    wait = idle = 0.0
    for r in bulk.state_rows.get(equipment_id, []):
        mins = _clip_interval_minutes(r.start_time, r.end_time, since, until)
        if r.state in _WAIT_STATES:
            wait += mins
        elif r.state in _IDLE_STATES:
            idle += mins
    return round(wait, 1), round(idle, 1)


def td_tu_pct_bulk(bulk: FleetBulkContext, equipment_id: int, since, until) -> tuple[float, float]:
    calendar = max(1.0, (until - since).total_seconds() / 60)
    unavailable = productive = 0.0
    for r in bulk.state_rows.get(equipment_id, []):
        mins = _clip_interval_minutes(r.start_time, r.end_time, since, until)
        if r.state in _UNAVAILABLE_STATES:
            unavailable += mins
        elif r.state in _PRODUCTIVE_STATES:
            productive += mins
    available = max(0.0, calendar - unavailable)
    td = min(100.0, max(0.0, (available / calendar) * 100)) if calendar > 0 else 0.0
    tu = min(100.0, max(0.0, (productive / available) * 100)) if available > 0 else 0.0
    return round(td, 1), round(tu, 1)


def td_tu_pct(session: Session, equipment_id: int, since, until) -> tuple[float, float]:
    rows = list(
        session.scalars(
            select(EquipmentStateRow).where(
                EquipmentStateRow.equipment_id == equipment_id,
                EquipmentStateRow.start_time < until,
                or_(EquipmentStateRow.end_time.is_(None), EquipmentStateRow.end_time > since),
            )
        ).all()
    )
    bulk = FleetBulkContext(state_rows={equipment_id: rows})
    return td_tu_pct_bulk(bulk, equipment_id, since, until)
