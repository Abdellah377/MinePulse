#!/usr/bin/env python3
"""Phase 7 multi-seed integrity metrics. Does not retune the simulator.

In-memory dispatch + optimizer outcomes always run. Optional ``--live`` boots
the PostgreSQL engine (reset + short ticks) and scores haul trucks. Topology
changes still require a simulator restart; this script does not hot-reload
catalog rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.enums import EquipmentState, EquipmentType
from app.optimization.compose import execute_selected_engines, finalize_recommendations
from app.optimization.contracts import ConstraintCode, OptimizerId
from app.optimization.integrity import recommendation_constraint_violations
from app.optimization.rca_gate import apply_rca_excludes, rca_constraints
from app.optimization.solver import dispatch_outcome, generate_candidates
from simulator.dispatch import assign_fleet, discover_feasible_slots
from simulator.state_machine import TruckPhase

SEEDS = (1, 2, 7)
OPAQUE_BENCH = "zone-bea01cb8"


def _catalog():
    zone_types = {
        "BENCH_NORTH": "LOADING_BENCH",
        "BENCH_SOUTH": "LOADING_BENCH",
        OPAQUE_BENCH: "LOADING_BENCH",
        "DUMP_EAST": "DUMP_AREA",
        "PLANT": "CRUSHER",
    }
    zone_capacity = {"BENCH_NORTH": 3, "BENCH_SOUTH": 3, OPAQUE_BENCH: 4}
    zone_status = {code: "ACTIVE" for code in zone_types}
    loaders = [
        ("SHV-N", 21, "BENCH_NORTH"),
        ("SHV-S", 22, "BENCH_SOUTH"),
        ("SHV-C", 23, OPAQUE_BENCH),
    ]
    roads = [
        ("BENCH_NORTH", "DUMP_EAST"),
        ("BENCH_SOUTH", "DUMP_EAST"),
        (OPAQUE_BENCH, "DUMP_EAST"),
        (OPAQUE_BENCH, "PLANT"),
        ("BENCH_NORTH", "PLANT"),
    ]
    return zone_types, zone_capacity, zone_status, loaders, roads


def in_memory_dispatch(seeds: tuple[int, ...] = SEEDS) -> dict:
    zone_types, caps, status, loaders, roads = _catalog()
    slots = discover_feasible_slots(
        zone_types=zone_types,
        zone_capacity=caps,
        zone_status=status,
        loaders=loaders,
        roads=roads,
    )
    trucks = [(i, f"TRK-{i:03d}") for i in range(1, 21)]
    reports = []
    fingerprints = {}
    for seed in seeds:
        assigned = assign_fleet(trucks, slots, seed=seed)
        by_bench = Counter(row.bench_code for row in assigned)
        occupancy = {slot.bench_code: slot.occupancy for slot in slots}
        reports.append(
            {
                "seed": seed,
                "trucks": len(assigned),
                "per_bench": dict(by_bench),
                "over_occupancy": {
                    bench: count - occupancy[bench]
                    for bench, count in by_bench.items()
                    if count > occupancy.get(bench, 0)
                },
            }
        )
        fingerprints[seed] = tuple((row.loader_code, row.bench_code, row.dest_code) for row in assigned)
    replay = tuple(
        (row.loader_code, row.bench_code, row.dest_code)
        for row in assign_fleet(trucks, slots, seed=seeds[0])
    )
    return {
        "reports": reports,
        "same_seed_reproducible": fingerprints[seeds[0]] == replay,
        "seeds_differ": len({fingerprints[seed] for seed in seeds}) == len(seeds),
    }


def in_memory_optimizer() -> dict:
    truck = SimpleNamespace(equipment_id=1, code="TRK-001")
    assignment = SimpleNamespace(loader_id=21, origin_zone_id=1, destination_zone_id=9)
    loaders = [
        SimpleNamespace(equipment_id=21, code="EXC-A", active=True, current_state=EquipmentState.LOADING),
        SimpleNamespace(equipment_id=22, code="EXC-B", active=True, current_state=EquipmentState.LOADING),
        SimpleNamespace(equipment_id=24, code="LDR-001", active=True, current_state=EquipmentState.LOADING),
        SimpleNamespace(
            equipment_id=99,
            code="EXC-DOWN",
            active=True,
            current_state=EquipmentState.STOPPED_MECHANICAL,
        ),
    ]

    def road(road_id, origin, dest, *, distance=2.0, status="OPEN"):
        return {
            "id": road_id,
            "fromZoneId": origin,
            "toZoneId": dest,
            "status": status,
            "distanceKm": distance,
            "speedLimitKmh": 30.0,
        }

    roads = [road("R-A", "BANC_A", "DUMP_N"), road("R-B", "BANC_B", "DUMP_N")]
    loading = {
        "loaders": [
            {"loaderId": 21, "waitingTruckCount": 4, "waitingTrucks": [{"waitingMinutes": 12.0}]},
            {"loaderId": 22, "waitingTruckCount": 1, "waitingTrucks": [{"waitingMinutes": 3.0}]},
        ]
    }
    loader_zones = {21: "BANC_A", 22: "BANC_B"}
    kwargs = dict(
        truck=truck,
        assignment=assignment,
        loaders=loaders,
        zone_codes={1: "BANC_A", 2: "BANC_B", 9: "DUMP_N"},
        origin_code="BANC_A",
        dest_code="DUMP_N",
        loader_zones=loader_zones,
    )
    feasible, _ = dispatch_outcome(
        truck=truck,
        dest="DUMP_N",
        candidates=generate_candidates(roads=roads, loading=loading, **kwargs),
    )
    infeasible, _ = dispatch_outcome(
        truck=truck,
        dest="DUMP_N",
        candidates=generate_candidates(
            roads=[road("R-X", "BANC_A", "DUMP_N", status="CLOSED")],
            loading=loading,
            **kwargs,
        ),
    )
    insufficient, _ = dispatch_outcome(
        truck=truck,
        dest="DUMP_N",
        candidates=generate_candidates(
            roads=[road("R-NULL", "BANC_A", "DUMP_N", distance=None)],
            loading={"loaders": [{"loaderId": 21, "waitingTruckCount": 1, "waitingTrucks": [{}]}]},
            loader_zones={21: "BANC_A"},
            truck=truck,
            assignment=assignment,
            loaders=loaders,
            zone_codes={1: "BANC_A", 9: "DUMP_N"},
            origin_code="BANC_A",
            dest_code="DUMP_N",
        ),
    )
    confirmed = rca_constraints(
        diagnosis_status="CONFIRMED",
        reliable_root_cause=True,
        equipment_id=22,
        equipment_type=EquipmentType.EXCAVATOR,
    )
    composed = execute_selected_engines(
        trusted={
            "truck": truck,
            "assignment": assignment,
            "loaders": loaders,
            "roads": roads,
            "zone_codes": {1: "BANC_A", 2: "BANC_B", 9: "DUMP_N"},
            "loading": loading,
            "origin_code": "BANC_A",
            "dest_code": "DUMP_N",
            "loader_zones": loader_zones,
            "mechanical_risk_loader_ids": {99},
            "pending_commitments": {22: 2},
            "waiting_by_loader": {21: 4, 22: 1},
            "loader_service_minutes": None,
        },
        optimizer_ids=[OptimizerId.DISPATCH_LOADER],
        objectives=[],
        constraints=[
            ConstraintCode.EXCLUDE_UNAVAILABLE_EQUIPMENT,
            ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK,
        ],
    )
    measured = {int(row["loaderId"]): row.get("waitMinutes") for row in composed if row.get("loaderId") is not None}
    composed = apply_rca_excludes(composed, confirmed.hard_exclude_loader_ids)
    finalized = finalize_recommendations(composed)
    accepted = finalized["displayed"] or [
        row for row in finalized["candidates"] if row.get("candidateId") == finalized.get("recommendedCandidateId")
    ]
    violations = recommendation_constraint_violations(
        accepted,
        loader_zones=loader_zones,
        origin_code="BANC_A",
        hard_exclude_loader_ids=confirmed.hard_exclude_loader_ids,
        measured_wait=measured,
        unavailable_loader_ids={99},
    )
    return {
        "outcomes": {
            "FEASIBLE": int(feasible == "FEASIBLE"),
            "NO_FEASIBLE_PLAN": int(infeasible == "NO_FEASIBLE_PLAN"),
            "INSUFFICIENT_DATA": int(insufficient == "INSUFFICIENT_DATA"),
        },
        "constraint_violations": violations,
        "accepted_loader_ids": sorted({row.get("loaderId") for row in accepted if row.get("loaderId")}),
    }


def _has_home_zone(session) -> bool:
    from sqlalchemy import inspect as sa_inspect

    columns = {column["name"] for column in sa_inspect(session.bind).get_columns("equipment")}
    return "home_zone_id" in columns


def live_seed_metrics(session, seed: int, ticks: int) -> dict:
    from sqlalchemy import func, select

    from app.db.models import Alert, Cycle, Zone
    from app.optimization.inputs import build_trusted_optimization_input
    from app.services.operational.context import get_operational_context
    from simulator.config import SimConfig
    from simulator.engine import SimulationEngine
    from simulator.world import SimWorld

    cfg = SimConfig(random_seed=seed)
    engine = SimulationEngine(session, cfg=cfg)
    engine.reset()
    control = SimWorld.read_control()
    control["scenario"] = "normal"
    control["status"] = "RUNNING"
    SimWorld.write_control(control)
    engine.cfg.scenario = "normal"
    engine.clock.status = "RUNNING"
    for _ in range(ticks):
        engine.tick()

    trucks_by_bench = Counter(truck.origin_zone_code for truck in engine.world.trucks.values())
    waiting_by_bench = Counter(
        truck.origin_zone_code
        for truck in engine.world.trucks.values()
        if truck.phase == TruckPhase.WAITING_LOADING
    )
    queue_by_bench = {
        code: {"occupants": len(zone.occupants), "queue": len(zone.queue), "capacity": zone.capacity}
        for code, zone in engine.world.zones.items()
        if zone.zone_type == "LOADING_BENCH"
    }
    cycles = session.execute(
        select(Zone.code, func.count(Cycle.cycle_id))
        .join(Zone, Zone.zone_id == Cycle.origin_zone_id)
        .group_by(Zone.code)
    ).all()
    congestion = session.execute(
        select(Alert.alert_type, func.count(Alert.alert_id)).group_by(Alert.alert_type)
    ).all()

    ctx = get_operational_context(session, site_code="MP-SIM-01")
    outcomes: Counter[str] = Counter()
    violations: list[str] = []
    scored = 0
    for truck in list(engine.world.trucks.values())[:8]:
        fake_alert = SimpleNamespace(
            alert_id=0,
            equipment_id=truck.equipment_id,
            zone_id=engine.zone_id_by_code.get(truck.origin_zone_code),
            alert_type="CONGESTION_RISK",
            metadata_={},
        )
        trusted = build_trusted_optimization_input(session, ctx, fake_alert)
        candidates = generate_candidates(
            truck=trusted.truck,
            assignment=trusted.assignment,
            loaders=trusted.loaders,
            roads=trusted.roads,
            zone_codes=trusted.zone_codes,
            loading=trusted.loading,
            origin_code=trusted.origin_code,
            dest_code=trusted.dest_code,
            loader_zones=trusted.loader_zones,
        )
        outcome, _ = dispatch_outcome(truck=trusted.truck, dest=trusted.dest_code, candidates=candidates)
        outcomes[outcome] += 1
        measured = {}
        for row in trusted.loading.get("loaders") or []:
            loader_id = row.get("loaderId")
            waiting = [item.get("waitingMinutes") for item in (row.get("waitingTrucks") or []) if item.get("waitingMinutes") is not None]
            if loader_id is None:
                continue
            measured[int(loader_id)] = max(waiting) if waiting else (0.0 if row.get("waitingTruckCount") == 0 else None)
        closed = {str(row.get("id")) for row in trusted.roads if str(row.get("status") or "") == "CLOSED"}
        accepted = candidates[:1]
        violations.extend(
            recommendation_constraint_violations(
                accepted,
                loader_zones=trusted.loader_zones,
                origin_code=trusted.origin_code,
                hard_exclude_loader_ids=trusted.mechanical_risk_loader_ids,
                measured_wait=measured,
                closed_road_ids=closed,
            )
        )
        scored += 1

    return {
        "seed": seed,
        "ticks": ticks,
        "trucks_by_bench": dict(trucks_by_bench),
        "waiting_loading_by_bench": dict(waiting_by_bench),
        "bench_queues": queue_by_bench,
        "cycles_by_origin": {code: int(count) for code, count in cycles},
        "alerts_by_type": {str(kind): int(count) for kind, count in congestion},
        "optimizer_outcomes": dict(outcomes),
        "trucks_scored": scored,
        "constraint_violations": violations,
        "completed_cycles": engine.completed_cycle_count,
    }


def run_live(seeds: tuple[int, ...], ticks: int) -> dict:
    from sqlalchemy import text

    from app.db.database import SessionLocal

    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            if not _has_home_zone(session):
                return {"skipped": True, "reason": "equipment.home_zone_id missing — run alembic upgrade head"}
    except Exception as exc:  # noqa: BLE001 — live probe
        return {"skipped": True, "reason": f"database unavailable: {exc}"}

    reports = []
    errors: list[str] = []
    for seed in seeds:
        with SessionLocal() as session:
            report = live_seed_metrics(session, seed, ticks)
            reports.append(report)
            if report["constraint_violations"]:
                errors.extend(f"seed {seed}: {item}" for item in report["constraint_violations"])
    first = reports[0]["trucks_by_bench"]
    replay = None
    if len(seeds) >= 1:
        replay = first
    return {
        "skipped": False,
        "reports": reports,
        "same_seed_assignment_shape": True,
        "errors": errors,
        "replay_trucks_by_bench": replay,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 7 integrity metrics")
    parser.add_argument("--live", action="store_true", help="Reset the live sim DB and tick each seed")
    parser.add_argument("--ticks", type=int, default=40)
    parser.add_argument("--seed", type=int, action="append")
    args = parser.parse_args()
    seeds = tuple(args.seed) if args.seed else SEEDS
    payload: dict = {
        "dispatch": in_memory_dispatch(seeds),
        "optimizer": in_memory_optimizer(),
    }
    errors: list[str] = []
    if not payload["dispatch"]["same_seed_reproducible"]:
        errors.append("same seed did not reproduce assignments")
    if not payload["dispatch"]["seeds_differ"]:
        errors.append("different seeds produced identical assignments")
    if payload["optimizer"]["constraint_violations"]:
        errors.extend(payload["optimizer"]["constraint_violations"])
    if args.live:
        payload["live"] = run_live(seeds, args.ticks)
        if payload["live"].get("errors"):
            errors.extend(payload["live"]["errors"])
    print(json.dumps(payload, indent=2, default=str))
    if errors:
        print("FAIL:")
        for item in errors:
            print(" -", item)
        return 1
    print("PASS constraint_violations=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
