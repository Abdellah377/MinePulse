#!/usr/bin/env python3
"""Simulator CLI — seed, run, reset, status."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.database import SessionLocal
from sqlalchemy import func, select
from app.db.models import Cycle, Equipment
from simulator.clock import get_sim_logger
from simulator.causal_scenarios import SCENARIO_SPECS, scenario_catalog, validate_trace
from simulator.config import SimConfig
from simulator.engine import SimulationEngine
from simulator.failure_population import FailurePopulationConfig
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


def cmd_generate_cycles(
    target_cycles: int,
    seed: int,
    max_ticks: int | None,
    sim_speed: float,
    verbose: bool,
    sample_every_ticks: int,
    with_failures: bool = False,
) -> int:
    """Generate a fresh, reproducible simulation-site dataset without wall sleeps."""

    if target_cycles < 1:
        raise ValueError("target_cycles must be positive")
    if sim_speed <= 0:
        raise ValueError("sim_speed must be positive")
    if sample_every_ticks < 1:
        raise ValueError("sample_every_ticks must be at least 1")
    if not verbose:
        log.setLevel(logging.WARNING)
    with SessionLocal() as session:
        seed_static_world(session)
        cfg = SimConfig(random_seed=seed)
        cfg.speed = sim_speed
        cfg.persistence_sample_every_ticks = sample_every_ticks
        cfg.failure_population = FailurePopulationConfig(enabled=with_failures)
        engine = SimulationEngine(session, cfg=cfg)
        engine.reset()
        engine.start()
        tick_limit = max_ticks or max(1_000, target_cycles * 12)
        ticks = 0
        while engine.completed_cycle_count < target_cycles and ticks < tick_limit:
            engine.tick()
            ticks += 1
        drain_ticks = 0
        if with_failures:
            engine.failure_population.stop_scheduling()
            max_drain_ticks = math.ceil(
                (
                    cfg.failure_population.degradation_max
                    + cfg.failure_population.repair_max
                )
                * 60.0
                / (cfg.tick_seconds * cfg.speed)
            ) + 10
            while engine.failure_population.has_active_incidents and drain_ticks < max_drain_ticks:
                engine.tick()
                ticks += 1
                drain_ticks += 1
        engine.pause()
        interruption = engine.interrupt_open_cycles(reason="DATASET_GENERATION_COMPLETE")
        simulation_equipment_ids = select(Equipment.equipment_id).where(
            Equipment.site_id == engine.site_id
        )
        completed = int(
            session.scalar(
                select(func.count())
                .select_from(Cycle)
                .where(
                    Cycle.status == "COMPLETED",
                    Cycle.truck_id.in_(simulation_equipment_ids),
                )
            )
            or 0
        )
        active = int(
            session.scalar(
                select(func.count())
                .select_from(Cycle)
                .where(
                    Cycle.status == "ACTIVE",
                    Cycle.truck_id.in_(simulation_equipment_ids),
                )
            )
            or 0
        )
        result = {
            "seed": seed,
            "sim_speed": sim_speed,
            "persistence_sample_every_ticks": sample_every_ticks,
            "target_completed_cycles": target_cycles,
            "completed_cycles": completed,
            "active_cycles": active,
            "interrupted_at_generation_end": interruption["cycles"],
            "ticks": ticks,
            "drain_ticks": drain_ticks,
            "sim_now": engine.clock.sim_now.isoformat(),
            "reached_target": completed >= target_cycles,
            "failures_enabled": with_failures,
            "failures_drained": not engine.failure_population.has_active_incidents,
            "failure_population": (
                engine.failure_population.developer_summary() if with_failures else None
            ),
        }
        print(json.dumps(result, indent=2))
        return 0 if result["reached_target"] and active == 0 and result["failures_drained"] else 2


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MinePulse FMS Simulator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="Seed static mine world")
    sub.add_parser("status", help="Show simulation status")
    sub.add_parser("reset", help="Clear dynamic data and reset clock")
    run_p = sub.add_parser("run", help="Run simulation loop")
    run_p.add_argument("--ticks", type=int, default=None, help="Max ticks (default: infinite)")
    generate_p = sub.add_parser(
        "generate-cycles",
        help="Reset the simulation site and generate a reproducible cycle dataset",
    )
    generate_p.add_argument("--target-cycles", type=int, default=1000)
    generate_p.add_argument("--seed", type=int, default=42)
    generate_p.add_argument("--max-ticks", type=int, default=None)
    generate_p.add_argument(
        "--sim-speed",
        type=float,
        default=60.0,
        help="simulated seconds per one-second engine tick (default: 60)",
    )
    generate_p.add_argument("--verbose", action="store_true", help="log every completed cycle")
    generate_p.add_argument(
        "--sample-every-ticks",
        type=int,
        default=2,
        help="persist position/telemetry every N ticks during batch generation",
    )
    generate_p.add_argument(
        "--with-failures",
        action="store_true",
        default=False,
        help="opt-in: enable the existing mechanical failure population during batch generation",
    )
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
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.cmd == "seed":
        return cmd_seed()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "reset":
        return cmd_reset()
    if args.cmd == "run":
        return cmd_run(args.ticks)
    if args.cmd == "generate-cycles":
        return cmd_generate_cycles(
            args.target_cycles,
            args.seed,
            args.max_ticks,
            args.sim_speed,
            args.verbose,
            args.sample_every_ticks,
            args.with_failures,
        )
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
