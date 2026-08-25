#!/usr/bin/env python3
"""Full simulation health check — invariants + injection acceptance chains."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select, text

from app.db.database import SessionLocal
from app.db.enums import AlertSource, AlertStatus, EquipmentState
from app.db.models import Alert, Equipment, EquipmentState as EquipmentStateRow, EquipmentTelemetry
from simulator.commands import SimulationCommand, append_command, clear_commands, clear_event_log
from simulator.control import read_control, write_control
from simulator.engine import SimulationEngine
from simulator.state_machine import TruckPhase


def _queue(action: str, target_id: str, duration_sec: int | None, target_type: str = "EQUIPMENT") -> None:
    append_command(
        SimulationCommand.create(
            target_type=target_type,
            target_id=target_id,
            action=action,
            duration_sec=duration_sec,
            parameters={},
        )
    )


def _ticks(engine: SimulationEngine, n: int) -> None:
    for _ in range(n):
        engine.tick()


def check_state_invariants(session) -> list[str]:
    errors: list[str] = []
    rows = session.execute(
        text(
            """
            SELECT e.code, es.state, et.speed_kmh, et.payload_t
            FROM equipment e
            JOIN equipment_telemetry et ON et.equipment_id = e.equipment_id
            JOIN equipment_states es ON es.equipment_id = e.equipment_id AND es.end_time IS NULL
            WHERE e.type = 'HAUL_TRUCK'
            """
        )
    ).all()
    for code, state, speed, payload in rows:
        if state == EquipmentState.NO_DATA.value and speed and float(speed) > 0:
            errors.append(f"{code}: NO_DATA but speed > 0")
        if state == EquipmentState.MOVING_EMPTY.value and payload and float(payload) > 50:
            errors.append(f"{code}: MOVING_EMPTY with large payload")
        if state == EquipmentState.MOVING_LOADED.value and payload is not None and float(payload) < 1:
            errors.append(f"{code}: MOVING_LOADED with zero payload")
    return errors


def check_api_db_consistency(session) -> list[str]:
    errors: list[str] = []
    equip = session.scalars(select(Equipment)).all()
    for eq in equip:
        open_row = session.scalar(
            select(EquipmentStateRow)
            .where(EquipmentStateRow.equipment_id == eq.equipment_id, EquipmentStateRow.end_time.is_(None))
            .order_by(EquipmentStateRow.start_time.desc())
        )
        if open_row and eq.current_state and open_row.state != eq.current_state:
            errors.append(f"{eq.code}: API current_state {eq.current_state} != open interval {open_row.state}")
    return errors


def acceptance_comm_loss(session) -> list[str]:
    errors: list[str] = []
    engine = SimulationEngine(session)
    engine.reset()
    clear_commands()
    clear_event_log()
    write_control({**read_control(), "status": "RUNNING", "mode": "MANUAL", "speed": 60})
    engine.clock.status = "RUNNING"
    engine.world.mode = "MANUAL"
    _ticks(engine, 3)

    _queue("COMMUNICATION_LOSS", "TRK-004", 10 * 60)
    _ticks(engine, 3)

    truck = engine.world.trucks.get("TRK-004")
    if not truck or not truck.comm_lost:
        errors.append("TRK-004 runtime comm_lost not set")

    eid = engine.equip_id_by_code.get("TRK-004")
    eq = session.get(Equipment, eid) if eid else None
    if eq and eq.current_state != EquipmentState.NO_DATA:
        errors.append(f"TRK-004 DB state expected NO_DATA, got {eq.current_state}")

    open_state = session.scalar(
        select(EquipmentStateRow).where(
            EquipmentStateRow.equipment_id == eid,
            EquipmentStateRow.end_time.is_(None),
        )
    )
    if not open_state or open_state.state != EquipmentState.NO_DATA:
        errors.append("TRK-004 missing open NO_DATA state interval")

    alerts = session.scalars(
        select(Alert).where(
            Alert.equipment_id == eid,
            Alert.alert_type == "COMM_LOSS",
            Alert.status != AlertStatus.RESOLVED,
        )
    ).all()
    if not alerts:
        errors.append("TRK-004 missing COMM_LOSS alert")

    before = session.execute(
        text("SELECT COUNT(*) FROM equipment_telemetry WHERE equipment_id=:eid"),
        {"eid": eid},
    ).scalar()
    _ticks(engine, 4)
    after = session.execute(
        text("SELECT COUNT(*) FROM equipment_telemetry WHERE equipment_id=:eid"),
        {"eid": eid},
    ).scalar()
    if after > before:
        errors.append("TRK-004 telemetry continued during comm loss")

    _queue("RESTORE", "TRK-004", None)
    _ticks(engine, 2)
    truck = engine.world.trucks.get("TRK-004")
    if truck and truck.comm_lost:
        errors.append("TRK-004 still comm_lost after RESTORE")

    resolved = session.scalars(
        select(Alert).where(Alert.equipment_id == eid, Alert.alert_type == "COMM_LOSS", Alert.status == AlertStatus.RESOLVED)
    ).all()
    if not resolved:
        errors.append("TRK-004 COMM_LOSS alert not resolved after RESTORE")

    session.rollback()
    return errors


def main() -> int:
    sections: dict[str, list[str]] = {}
    with SessionLocal() as session:
        for name, fn in [
            ("State machine consistency", check_state_invariants),
            ("API propagation", check_api_db_consistency),
            ("Fault injections (COMM_LOSS)", acceptance_comm_loss),
        ]:
            print(f"=== {name} ===")
            try:
                errs = fn(session)
            except Exception as exc:  # noqa: BLE001
                errs = [f"EXCEPTION: {exc}"]
                session.rollback()
            sections[name] = errs
            if errs:
                for e in errs:
                    print(f"  FAIL: {e}")
            else:
                print("  PASS")

    print("\nSIMULATION HEALTH")
    all_fail = False
    for name, errs in sections.items():
        status = "PASS" if not errs else "FAIL"
        if errs:
            all_fail = True
        print(f"  {name}: {status}")

    overall = "FAIL" if all_fail else "PASS"
    print(f"\nOverall: {overall}")
    return 1 if all_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
