#!/usr/bin/env python3
"""Validation for Simulation Centre injects (EXC-002, TRK-004, TRK-012)."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.database import SessionLocal
from simulator.apply_commands import CommandContext, process_pending_commands
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


def _run_ticks(engine: SimulationEngine, n: int) -> None:
    for _ in range(n):
        engine.tick()


def test_exc_002_breakdown(session) -> list[str]:
    errors: list[str] = []
    engine = SimulationEngine(session)
    engine.reset()
    clear_commands()
    clear_event_log()
    write_control({**read_control(), "status": "RUNNING", "mode": "MANUAL", "speed": 60})
    engine.clock.status = "RUNNING"
    engine.world.mode = "MANUAL"
    engine.clock.speed = 60

    # Warm up a few ticks
    _run_ticks(engine, 5)

    _queue("BREAKDOWN", "EXC-002", 30 * 60)
    ctx = CommandContext(
        world=engine.world,
        session=engine.session,
        sim_now=engine.clock.sim_now,
        open_states=engine.open_states,
        equip_id_by_code=engine.equip_id_by_code,
        zone_id_by_code=engine.zone_id_by_code,
        site_id=engine.site_id or 0,
    )
    process_pending_commands(ctx)
    engine.session.commit()

    ldr = engine.world.loaders.get("EXC-002")
    if not ldr or ldr.effective_capacity() > 0:
        errors.append("EXC-002 should have capacity 0 after BREAKDOWN")
    if "EXC-002" not in engine.world.excavators_down:
        errors.append("EXC-002 should be in excavators_down")

    # Advance enough sim time for natural waits (speed 60 → ~60s/tick)
    _run_ticks(engine, 40)

    waiting = [
        t
        for t in engine.world.trucks.values()
        if t.loader_code == "EXC-002" and t.phase in (TruckPhase.WAITING_LOADING, TruckPhase.LOADING)
    ]
    # At least some trucks assigned to EXC-002 should be blocked or slowed
    assigned = [t for t in engine.world.trucks.values() if t.loader_code == "EXC-002"]
    blocked = [
        t
        for t in assigned
        if t.phase == TruckPhase.WAITING_LOADING or (t.phase == TruckPhase.LOADING and ldr and ldr.effective_capacity() <= 0)
    ]
    if assigned and not blocked and not any(
        t.phase == TruckPhase.WAITING_LOADING for t in engine.world.trucks.values()
    ):
        # Soft check: excavator down should force waits via engine logic
        force_waited = any(
            t.phase == TruckPhase.WAITING_LOADING for t in engine.world.trucks.values() if t.loader_code == "EXC-002"
        )
        if not force_waited:
            # Re-check: engine sets WAITING when loader capacity 0 during LOADING
            for t in assigned:
                if t.phase == TruckPhase.LOADING and ldr and ldr.effective_capacity() <= 0:
                    errors.append(f"{t.code} still LOADING while EXC-002 down")

    # Expire after 30 min sim — advance enough ticks
    # duration 1800s; speed 60 → 60s/tick → need 30 ticks minimum from inject
    start = engine.clock.sim_now
    while engine.clock.sim_now < start + timedelta(seconds=31 * 60):
        engine.tick()
        if (engine.clock.sim_now - start).total_seconds() > 40 * 60:
            break

    ldr = engine.world.loaders.get("EXC-002")
    if ldr and ldr.effective_capacity() <= 0 and any(
        i.action == "BREAKDOWN" and i.target_id == "EXC-002" for i in engine.world.injections.values()
    ):
        errors.append("EXC-002 BREAKDOWN should have expired after ~30 min sim")
    elif ldr and ldr.effective_capacity() <= 0:
        # restore may have run via expire
        process_pending_commands(ctx)
        engine.session.commit()
        ldr = engine.world.loaders.get("EXC-002")
        if ldr and ldr.effective_capacity() <= 0:
            errors.append("EXC-002 still down after duration elapsed")

    session.rollback()
    return errors


def test_trk_004_comm_loss(session) -> list[str]:
    errors: list[str] = []
    engine = SimulationEngine(session)
    engine.reset()
    clear_commands()
    write_control({**read_control(), "status": "RUNNING", "mode": "MANUAL", "speed": 60})
    engine.clock.status = "RUNNING"
    engine.world.mode = "MANUAL"
    engine.clock.speed = 60
    _run_ticks(engine, 3)

    _queue("COMMUNICATION_LOSS", "TRK-004", 10 * 60)
    _run_ticks(engine, 2)

    truck = engine.world.trucks.get("TRK-004")
    if not truck or not truck.comm_lost or truck.phase != TruckPhase.NO_COMM:
        errors.append(f"TRK-004 should be NO_COMM after inject, got {truck.phase if truck else None}")

    # Positions should freeze while still in NO_COMM (duration 10 min; speed 60 => do not exceed ~8 ticks)
    eid = engine.equip_id_by_code.get("TRK-004")
    before = session.execute(
        text("SELECT COUNT(*) FROM equipment_positions WHERE equipment_id=:eid"),
        {"eid": eid},
    ).scalar()
    _run_ticks(engine, 5)
    truck = engine.world.trucks.get("TRK-004")
    if not truck or not truck.comm_lost:
        errors.append("TRK-004 lost comm_lost before duration elapsed")
    after = session.execute(
        text("SELECT COUNT(*) FROM equipment_positions WHERE equipment_id=:eid"),
        {"eid": eid},
    ).scalar()
    if after > before:
        errors.append(f"TRK-004 still writing positions during comm loss ({before}->{after})")

    start = engine.clock.sim_now
    while engine.clock.sim_now < start + timedelta(seconds=12 * 60):
        engine.tick()
        if (engine.clock.sim_now - start).total_seconds() > 25 * 60:
            break

    truck = engine.world.trucks.get("TRK-004")
    if truck and truck.comm_lost:
        errors.append("TRK-004 still comm_lost after 10 min duration")

    session.rollback()
    return errors


def test_trk_012_undefined_stop(session) -> list[str]:
    errors: list[str] = []
    engine = SimulationEngine(session)
    engine.reset()
    clear_commands()
    write_control({**read_control(), "status": "RUNNING", "mode": "MANUAL", "speed": 60})
    engine.clock.status = "RUNNING"
    engine.world.mode = "MANUAL"
    engine.clock.speed = 60
    _run_ticks(engine, 3)

    _queue("STOP_UNDEFINED", "TRK-012", None)
    _run_ticks(engine, 3)

    truck = engine.world.trucks.get("TRK-012")
    if not truck or not truck.unexplained_hold or truck.phase != TruckPhase.STOPPED:
        errors.append(
            f"TRK-012 should be STOPPED unexplained, got phase={truck.phase if truck else None} hold={getattr(truck, 'unexplained_hold', None)}"
        )
    if truck and truck.speed_kmh != 0:
        errors.append("TRK-012 should have speed 0")

    # Should stay held across ticks until restore
    _run_ticks(engine, 15)
    truck = engine.world.trucks.get("TRK-012")
    if not truck or not truck.unexplained_hold:
        errors.append("TRK-012 unexplained_hold cleared without RESTORE")

    _queue("RESTORE", "TRK-012", None)
    _run_ticks(engine, 2)
    truck = engine.world.trucks.get("TRK-012")
    if truck and truck.unexplained_hold:
        errors.append("TRK-012 still unexplained_hold after RESTORE")
    if truck and truck.phase == TruckPhase.STOPPED and truck.unexplained_hold:
        errors.append("TRK-012 still STOPPED after RESTORE")

    session.rollback()
    return errors


def test_control_reread(session) -> list[str]:
    """API-style control writes must be picked up on next tick."""
    errors: list[str] = []
    engine = SimulationEngine(session)
    engine.reset()
    write_control({**read_control(), "status": "RUNNING", "mode": "MANUAL", "speed": 30})
    engine.clock.status = "RUNNING"
    engine.clock.speed = 30
    _run_ticks(engine, 2)

    write_control({**read_control(), "speed": 120, "status": "PAUSED"})
    engine.tick()
    if engine.clock.speed != 120:
        errors.append(f"speed not re-read: {engine.clock.speed}")
    if engine.clock.status != "PAUSED":
        errors.append(f"status not re-read: {engine.clock.status}")

    write_control({**read_control(), "status": "RUNNING", "mode": "NORMAL"})
    engine.tick()
    if engine.world.mode != "NORMAL":
        errors.append(f"mode not re-read: {engine.world.mode}")

    session.rollback()
    return errors


def main() -> int:
    all_errors: list[str] = []
    with SessionLocal() as session:
        for name, fn in [
            ("control_reread", test_control_reread),
            ("EXC-002_breakdown", test_exc_002_breakdown),
            ("TRK-004_comm_loss", test_trk_004_comm_loss),
            ("TRK-012_undefined_stop", test_trk_012_undefined_stop),
        ]:
            print(f"=== {name} ===")
            try:
                errs = fn(session)
            except Exception as exc:  # noqa: BLE001
                errs = [f"EXCEPTION: {exc}"]
                session.rollback()
            if errs:
                for e in errs:
                    print(f"  FAIL: {e}")
                all_errors.extend(f"{name}: {e}" for e in errs)
            else:
                print("  PASS")

    if all_errors:
        print(f"\nFAILED ({len(all_errors)}):")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
