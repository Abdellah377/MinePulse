"""Central state transition service — single path for simulator, commands, and recovery."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.db.models import Equipment, EquipmentState as EquipmentStateRow
from simulator.generators.events import emit_system_event
from simulator.geometry import ZoneGeom, resolve_zone_id
from simulator.loaders import LoaderRuntime
from simulator.state_machine import PHASE_TO_DB, TruckPhase, TruckRuntime

if TYPE_CHECKING:
    pass

OpenStateRef = int | EquipmentStateRow


def _close_open_interval(
    session: Session,
    open_states: dict[str, OpenStateRef],
    code: str,
    sim_now: datetime,
) -> None:
    prev = open_states.pop(code, None)
    if prev is None:
        return
    row = prev if isinstance(prev, EquipmentStateRow) else session.get(EquipmentStateRow, prev)
    if row and row.end_time is None:
        row.end_time = sim_now
        row.duration_sec = int((sim_now - row.start_time).total_seconds())


def truck_db_state(truck: TruckRuntime) -> EquipmentState:
    if truck.mechanical_hold:
        return EquipmentState.STOPPED_MECHANICAL
    if truck.in_maintenance:
        return EquipmentState.MAINTENANCE
    if truck.unexplained_hold:
        return EquipmentState.STOPPED_UNDEFINED
    return PHASE_TO_DB[truck.phase]


def loader_db_state(ldr: LoaderRuntime) -> EquipmentState:
    if ldr.mechanical_breakdown or not ldr.available:
        return EquipmentState.STOPPED_MECHANICAL
    if ldr.communication_lost:
        return EquipmentState.NO_DATA
    if ldr.effective_capacity() > 0:
        return EquipmentState.LOADING
    return EquipmentState.STOPPED_OPERATIONAL


def transition_truck(
    session: Session,
    open_states: dict[str, OpenStateRef],
    truck: TruckRuntime,
    sim_now: datetime,
    site_id: int,
    *,
    source: str = "SIMULATOR",
    message: str | None = None,
    zones: dict[str, ZoneGeom] | None = None,
    equipment: Equipment | None = None,
) -> EquipmentStateRow:
    """Close previous interval, open new one, emit system event."""
    _close_open_interval(session, open_states, truck.code, sim_now)

    zone_id = resolve_zone_id(
        session,
        site_id,
        truck.lng,
        truck.lat,
        moving=truck.is_moving() and truck.road_progress < 1.0,
        zones=zones,
    )
    reason_confirmed = not truck.unexplained_hold
    reason_code = None
    if truck.unexplained_hold:
        reason_code = "UNDEFINED"
    elif truck.mechanical_hold:
        reason_code = "MECHANICAL"
    elif truck.in_maintenance:
        reason_code = "MAINTENANCE"

    new_state = truck_db_state(truck)
    row = EquipmentStateRow(
        equipment_id=truck.equipment_id,
        state=new_state,
        start_time=sim_now,
        zone_id=zone_id,
        reason_confirmed=reason_confirmed,
        reason_code=reason_code,
    )
    session.add(row)
    session.flush()
    open_states[truck.code] = row

    eq = equipment if equipment is not None else session.get(Equipment, truck.equipment_id)
    if eq:
        eq.current_state = new_state

    evt_msg = message or f"{truck.code} → {new_state.value} ({source})"
    emit_system_event(session, sim_now, "EQUIPMENT_STATE_CHANGED", truck.equipment_id, evt_msg)
    return row


def transition_loader(
    session: Session,
    open_states: dict[str, OpenStateRef],
    ldr: LoaderRuntime,
    sim_now: datetime,
    *,
    source: str = "SIMULATOR",
    message: str | None = None,
    equipment: Equipment | None = None,
) -> EquipmentStateRow:
    """Transition loader/excavator equipment state."""
    _close_open_interval(session, open_states, ldr.code, sim_now)

    new_state = loader_db_state(ldr)
    row = EquipmentStateRow(
        equipment_id=ldr.equipment_id,
        state=new_state,
        start_time=sim_now,
        zone_id=None,
        reason_confirmed=True,
        reason_code="MECHANICAL" if ldr.mechanical_breakdown else None,
    )
    session.add(row)
    session.flush()
    open_states[ldr.code] = row

    eq = equipment if equipment is not None else session.get(Equipment, ldr.equipment_id)
    if eq:
        eq.current_state = new_state

    evt_msg = message or f"{ldr.code} → {new_state.value} ({source})"
    emit_system_event(session, sim_now, "EQUIPMENT_STATE_CHANGED", ldr.equipment_id, evt_msg)
    return row


def close_truck_state_interval(
    session: Session,
    open_states: dict[str, OpenStateRef],
    truck: TruckRuntime,
    sim_now: datetime,
) -> None:
    """Close open state interval without opening a new one (used during recovery)."""
    _close_open_interval(session, open_states, truck.code, sim_now)


def close_loader_state_interval(
    session: Session,
    open_states: dict[str, OpenStateRef],
    ldr: LoaderRuntime,
    sim_now: datetime,
) -> None:
    _close_open_interval(session, open_states, ldr.code, sim_now)
