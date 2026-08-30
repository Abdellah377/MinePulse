#!/usr/bin/env python3
"""Lightweight profiler for simulator generate-cycles. Does not train ML."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import Session

from simulator.cli import cmd_generate_cycles


class Timer:
    def __init__(self) -> None:
        self.totals: dict[str, float] = defaultdict(float)
        self.counts: dict[str, int] = defaultdict(int)

    def wrap(self, name: str, fn):
        def inner(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.totals[name] += time.perf_counter() - t0
                self.counts[name] += 1

        return inner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-cycles", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sim-speed", type=float, default=60)
    parser.add_argument("--sample-every-ticks", type=int, default=2)
    parser.add_argument("--with-failures", action="store_true")
    args = parser.parse_args()
    timer = Timer()

    orig_commit = Session.commit
    orig_flush = Session.flush
    orig_get = Session.get
    Session.commit = timer.wrap("session.commit", orig_commit)
    Session.flush = timer.wrap("session.flush", orig_flush)
    Session.get = timer.wrap("session.get", orig_get)

    import simulator.control as control
    import simulator.commands as commands
    import simulator.geometry as geometry
    import simulator.engine as engine_mod
    import simulator.generators.telemetry as telemetry
    import simulator.generators.tyres as tyres
    import simulator.transition_service as transitions

    control.write_heartbeat = timer.wrap("write_heartbeat", control.write_heartbeat)
    control.write_control = timer.wrap("write_control", control.write_control)
    control.read_control = timer.wrap("read_control", control.read_control)
    commands.load_all_commands = timer.wrap("load_all_commands", commands.load_all_commands)
    geometry.resolve_zone_id = timer.wrap("resolve_zone_id", geometry.resolve_zone_id)
    telemetry.build_telemetry = timer.wrap("build_telemetry", telemetry.build_telemetry)
    tyres.tyre_rows = timer.wrap("tyre_rows", tyres.tyre_rows)
    transitions.transition_truck = timer.wrap("transition_truck", transitions.transition_truck)
    orig_tick = engine_mod.SimulationEngine.tick
    engine_mod.SimulationEngine.tick = timer.wrap("engine.tick", orig_tick)
    for name in (
        "_persist_control",
        "_flush_telemetry_batch",
        "_end_tick_persist",
        "_write_position",
        "_write_telemetry",
        "_write_tyres",
        "_update_position",
        "_load_commands",
        "_sync_control_from_disk",
    ):
        fn = getattr(engine_mod.SimulationEngine, name)
        setattr(engine_mod.SimulationEngine, name, timer.wrap(name, fn))

    wall0 = time.perf_counter()
    rc = cmd_generate_cycles(
        args.target_cycles,
        args.seed,
        None,
        args.sim_speed,
        False,
        args.sample_every_ticks,
        args.with_failures,
    )
    wall = time.perf_counter() - wall0

    rows = []
    for name, total in sorted(timer.totals.items(), key=lambda item: -item[1]):
        rows.append(
            {
                "name": name,
                "seconds": round(total, 3),
                "calls": timer.counts[name],
                "pct_of_wall": round(100.0 * total / wall, 1) if wall else None,
            }
        )
    report = {
        "wall_seconds": round(wall, 3),
        "return_code": rc,
        "target_cycles": args.target_cycles,
        "with_failures": args.with_failures,
        "breakdown": rows,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
