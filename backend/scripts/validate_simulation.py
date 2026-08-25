#!/usr/bin/env python3
"""End-to-end validation: reset → run ticks → assert DB integrity + bootstrap richness."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.database import SessionLocal
from app.api.routes.bootstrap import bootstrap
from simulator.engine import SimulationEngine
from simulator.world import SimWorld


def main() -> int:
    errors: list[str] = []

    with SessionLocal() as session:
        engine = SimulationEngine(session)
        engine.reset()
        control = SimWorld.read_control()
        control["scenario"] = "normal"
        control["status"] = "RUNNING"
        SimWorld.write_control(control)
        engine.cfg.scenario = "normal"
        engine.clock.status = "RUNNING"

        for _ in range(80):
            engine.tick()

        pos = session.scalar(text("SELECT COUNT(*) FROM equipment_positions"))
        tel = session.scalar(text("SELECT COUNT(*) FROM equipment_telemetry"))
        states = session.scalar(text("SELECT COUNT(*) FROM equipment_states"))
        stages = session.scalar(text("SELECT COUNT(*) FROM cycle_stages"))
        distinct_stages = session.scalar(text("SELECT COUNT(DISTINCT stage) FROM cycle_stages"))
        null_loader = session.scalar(
            text("SELECT COUNT(*) FROM cycles WHERE loader_id IS NULL AND status='COMPLETED'")
        )
        bad_dist = session.scalar(
            text("SELECT COUNT(*) FROM trips WHERE distance_km = 4.2 AND status='COMPLETED'")
        )
        moving_zoned = session.scalar(
            text(
                """
                SELECT COUNT(*) FROM equipment_positions ep
                JOIN equipment_states es ON es.equipment_id = ep.equipment_id
                  AND es.end_time IS NULL
                WHERE ep.zone_id IS NOT NULL
                  AND es.state IN ('MOVING_LOADED','MOVING_EMPTY')
                  AND ep.ts = (SELECT MAX(ts) FROM equipment_positions WHERE equipment_id = ep.equipment_id)
                """
            )
        )

        if pos < 100:
            errors.append(f"too few positions: {pos}")
        if tel < 100:
            errors.append(f"too few telemetry: {tel}")
        if states < 20:
            errors.append(f"too few states: {states}")
        if stages < 10:
            errors.append(f"too few cycle_stages: {stages}")
        if (distinct_stages or 0) < 3:
            errors.append(f"cycle stages not diverse: {distinct_stages}")
        if null_loader and null_loader > 0:
            errors.append(f"completed cycles with NULL loader_id: {null_loader}")
        if bad_dist and bad_dist > 0:
            errors.append(f"trips still using hard-coded 4.2 km: {bad_dist}")

        payload = bootstrap(session)
        if len(payload.get("timelineSegments", [])) < 10:
            errors.append(f"bootstrap timeline too short: {len(payload.get('timelineSegments', []))}")
        if len(payload.get("equipment", [])) < 20:
            errors.append("bootstrap equipment incomplete")
        if not payload.get("simNow"):
            errors.append("bootstrap missing simNow")

        print(f"positions={pos} telemetry={tel} states={states} stages={stages} stage_kinds={distinct_stages}")
        print(f"timeline={len(payload.get('timelineSegments', []))} simNow={payload.get('simNow')}")
        print(f"moving_with_zone={moving_zoned} (expect low)")

    # Determinism smoke: two short runs with same seed produce same first truck fuel
    fuels = []
    for _ in range(2):
        with SessionLocal() as session:
            engine = SimulationEngine(session)
            engine.reset()
            c = SimWorld.read_control()
            c["scenario"] = "normal"
            c["status"] = "RUNNING"
            SimWorld.write_control(c)
            engine.cfg.scenario = "normal"
            engine.clock.status = "RUNNING"
            for _ in range(5):
                engine.tick()
            fuels.append(round(engine.world.trucks["TRK-001"].fuel_pct, 4))
    if fuels[0] != fuels[1]:
        errors.append(f"non-deterministic fuel after 5 ticks: {fuels}")
    else:
        print(f"determinism OK fuel={fuels[0]}")

    if errors:
        print("FAIL:")
        for e in errors:
            print(" -", e)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
