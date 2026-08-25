#!/usr/bin/env python3
"""Simulator CLI — seed, run, reset, status."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.database import SessionLocal
from simulator.clock import get_sim_logger
from simulator.engine import SimulationEngine
from simulator.seed import seed_static_world
from simulator.world import SimWorld

log = get_sim_logger()


def cmd_seed() -> int:
    with SessionLocal() as session:
        seed_static_world(session)
    return 0


def cmd_status() -> int:
    control = SimWorld.read_control()
    print(f"Status: {control.get('status')}")
    print(f"Sim time: {control.get('sim_now')}")
    print(f"Speed: {control.get('speed')}x")
    print(f"Scenario: {control.get('scenario')}")
    return 0


def cmd_reset() -> int:
    with SessionLocal() as session:
        engine = SimulationEngine(session)
        engine.reset()
    log.info("Simulation reset complete")
    return 0


def cmd_run(ticks: int | None) -> int:
    with SessionLocal() as session:
        engine = SimulationEngine(session)
        engine.start()
        n = 0
        try:
            while ticks is None or n < ticks:
                engine.tick()
                n += 1
                time.sleep(engine.cfg.tick_seconds)
        except KeyboardInterrupt:
            engine.pause()
            log.info("Simulator paused")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MinePulse FMS Simulator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="Seed static mine world")
    sub.add_parser("status", help="Show simulation status")
    sub.add_parser("reset", help="Clear dynamic data and reset clock")
    run_p = sub.add_parser("run", help="Run simulation loop")
    run_p.add_argument("--ticks", type=int, default=None, help="Max ticks (default: infinite)")
    args = parser.parse_args()

    if args.cmd == "seed":
        return cmd_seed()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "reset":
        return cmd_reset()
    if args.cmd == "run":
        return cmd_run(args.ticks)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
