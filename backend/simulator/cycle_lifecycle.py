"""Simulator-site lifecycle reconciliation for unfinished operational work."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Cycle, CycleStage, Equipment, Trip
from app.db.models.telemetry import EquipmentState as EquipmentStateRow


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _safe_end(start: datetime, requested: datetime) -> datetime:
    start_aware = _aware(start)
    requested_aware = _aware(requested)
    return max(start_aware, requested_aware)


def _metadata(row, *, reason: str) -> None:
    metadata = dict(getattr(row, "metadata_", None) or {})
    metadata.update({"lifecycle": "INTERRUPTED", "interruption_reason": reason})
    row.metadata_ = metadata


def interrupt_active_simulation_cycles(
    session: Session,
    *,
    site_id: int,
    interrupted_at: datetime,
    reason: str,
) -> dict[str, int]:
    """Reconcile ACTIVE rows for one site after non-resumable engine loss.

    The simulator runtime is intentionally in memory.  A new engine therefore
    cannot safely resume an old persisted cycle.  Such rows remain auditable as
    INTERRUPTED and stay excluded from the ML training target.
    """

    equipment_ids = select(Equipment.equipment_id).where(Equipment.site_id == site_id)
    cycles = list(
        session.scalars(
            select(Cycle).where(Cycle.truck_id.in_(equipment_ids), Cycle.status == "ACTIVE")
        ).all()
    )
    cycle_ids = [cycle.cycle_id for cycle in cycles]

    stages: list[CycleStage] = []
    if cycle_ids:
        stages = list(
            session.scalars(
                select(CycleStage).where(
                    CycleStage.cycle_id.in_(cycle_ids), CycleStage.end_time.is_(None)
                )
            ).all()
        )
    for stage in stages:
        end = _safe_end(stage.start_time, interrupted_at)
        stage.end_time = end
        stage.duration_sec = int((end - _aware(stage.start_time)).total_seconds())
        _metadata(stage, reason=reason)

    trips = list(
        session.scalars(
            select(Trip).where(Trip.truck_id.in_(equipment_ids), Trip.status == "ACTIVE")
        ).all()
    )
    for trip in trips:
        trip.end_time = _safe_end(trip.start_time, interrupted_at)
        trip.status = "INTERRUPTED"
        _metadata(trip, reason=reason)

    for cycle in cycles:
        cycle.completed_at = _safe_end(cycle.started_at, interrupted_at)
        cycle.total_duration_sec = None
        cycle.status = "INTERRUPTED"
        _metadata(cycle, reason=reason)

    state_rows = list(
        session.scalars(
            select(EquipmentStateRow).where(
                EquipmentStateRow.equipment_id.in_(equipment_ids),
                EquipmentStateRow.end_time.is_(None),
            )
        ).all()
    )
    for state in state_rows:
        state.end_time = _safe_end(state.start_time, interrupted_at)
        state.duration_sec = int((state.end_time - _aware(state.start_time)).total_seconds())

    session.flush()
    return {
        "cycles": len(cycles),
        "cycle_stages": len(stages),
        "trips": len(trips),
        "equipment_states": len(state_rows),
    }


def interrupt_active_truck_work(
    session: Session,
    *,
    cycle_id: int | None,
    stage_id: int | None,
    trip_id: int | None,
    interrupted_at: datetime,
    reason: str,
) -> None:
    """Interrupt one truck's in-memory work when a mechanical stop occurs."""

    if stage_id is not None:
        stage = session.get(CycleStage, stage_id)
        if stage is not None and stage.end_time is None:
            end = _safe_end(stage.start_time, interrupted_at)
            stage.end_time = end
            stage.duration_sec = int((end - _aware(stage.start_time)).total_seconds())
            _metadata(stage, reason=reason)
    if trip_id is not None:
        trip = session.get(Trip, trip_id)
        if trip is not None and trip.status == "ACTIVE":
            trip.end_time = _safe_end(trip.start_time, interrupted_at)
            trip.status = "INTERRUPTED"
            _metadata(trip, reason=reason)
    if cycle_id is not None:
        cycle = session.get(Cycle, cycle_id)
        if cycle is not None and cycle.status == "ACTIVE":
            cycle.completed_at = _safe_end(cycle.started_at, interrupted_at)
            cycle.total_duration_sec = None
            cycle.status = "INTERRUPTED"
            _metadata(cycle, reason=reason)
    session.flush()
