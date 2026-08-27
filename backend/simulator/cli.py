#!/usr/bin/env python3
"""Simulator CLI — seed, run, reset, status."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.database import SessionLocal
from simulator.clock import get_sim_logger
from simulator.causal_scenarios import SCENARIO_SPECS, scenario_catalog, validate_trace
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


def cmd_causal_list() -> int:
    print(json.dumps(scenario_catalog(include_hidden=True), indent=2))
    return 0


def cmd_causal_run(
    scenario_id: str,
    target_id: str,
    duration_min: float | None,
    seed: int,
    ticks: int | None,
    realtime: bool,
) -> int:
    """Prepare persisted evidence without passing hidden truth to the AI."""
    with SessionLocal() as session:
        engine = SimulationEngine(session)
        status = engine.activate_causal_scenario(
            scenario_id,
            target_id,
            duration_min=duration_min,
            seed=seed,
        )
        engine.start()
        run = engine.causal_scenarios.active[status["run_id"]]
        tick_count = ticks or (
            math.ceil(run.duration_sec / (engine.cfg.tick_seconds * engine.clock.speed)) + 2
        )
        for _ in range(tick_count):
            engine.tick()
            if realtime:
                time.sleep(engine.cfg.tick_seconds)
        engine.pause()
        result = {
            "run": run.developer_status(include_hidden=True),
            "initial_status": status,
            "ticks": tick_count,
            "data_quality_warnings": validate_trace(run),
            "note": "Hidden truth stayed in simulator memory; LangGraph must be run separately from persisted operational data.",
        }
        print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MinePulse FMS Simulator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="Seed static mine world")
    sub.add_parser("status", help="Show simulation status")
    sub.add_parser("reset", help="Clear dynamic data and reset clock")
    run_p = sub.add_parser("run", help="Run simulation loop")
    run_p.add_argument("--ticks", type=int, default=None, help="Max ticks (default: infinite)")
    sub.add_parser("causal-list", help="List causal diagnostic scenarios")
    causal_p = sub.add_parser(
        "causal-run",
        help="Run one causal scenario and persist its observable evidence",
    )
    causal_p.add_argument("--scenario", choices=sorted(SCENARIO_SPECS), required=True)
    causal_p.add_argument("--target", required=True)
    causal_p.add_argument("--duration-min", type=float, default=None)
    causal_p.add_argument("--seed", type=int, default=42)
    causal_p.add_argument("--ticks", type=int, default=None)
    causal_p.add_argument(
        "--realtime",
        action="store_true",
        help="Sleep between ticks so progression can be watched in the UI",
    )
    args = parser.parse_args()

    if args.cmd == "seed":
        return cmd_seed()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "reset":
        return cmd_reset()
    if args.cmd == "run":
        return cmd_run(args.ticks)
    if args.cmd == "causal-list":
        return cmd_causal_list()
    if args.cmd == "causal-run":
        return cmd_causal_run(
            args.scenario,
            args.target,
            args.duration_min,
            args.seed,
            args.ticks,
            args.realtime,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
