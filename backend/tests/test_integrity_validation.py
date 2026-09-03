"""Phase 7 integrity metrics: multi-seed dispatch, optimizer outcomes, zero violations."""

from collections import Counter
from types import SimpleNamespace

from app.db.enums import EquipmentState, EquipmentType
from app.optimization.compose import execute_selected_engines, finalize_recommendations
from app.optimization.contracts import ConstraintCode, OptimizerId
from app.optimization.integrity import recommendation_constraint_violations
from app.optimization.rca_gate import apply_rca_excludes, rca_constraints
from app.optimization.solver import dispatch_outcome, generate_candidates
from simulator.dispatch import assign_fleet, discover_feasible_slots


OPAQUE_BENCH = "zone-bea01cb8"
SEEDS = (1, 2, 7)


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


def _dispatch_metrics(seed: int) -> dict:
    zone_types, caps, status, loaders, roads = _catalog()
    slots = discover_feasible_slots(
        zone_types=zone_types,
        zone_capacity=caps,
        zone_status=status,
        loaders=loaders,
        roads=roads,
    )
    trucks = [(i, f"TRK-{i:03d}") for i in range(1, 21)]
    assigned = assign_fleet(trucks, slots, seed=seed)
    by_bench = Counter(row.bench_code for row in assigned)
    occupancy = {slot.bench_code: slot.occupancy for slot in slots}
    over_occupancy = {
        bench: count - occupancy[bench]
        for bench, count in by_bench.items()
        if count > occupancy.get(bench, 0)
    }
    return {
        "seed": seed,
        "trucks": len(assigned),
        "per_bench": dict(by_bench),
        "over_occupancy": over_occupancy,
        "fingerprint": tuple((row.loader_code, row.bench_code, row.dest_code) for row in assigned),
    }


def _open_road(road_id: str, origin: str, dest: str, *, distance: float | None = 2.0, status: str = "OPEN"):
    return {
        "id": road_id,
        "fromZoneId": origin,
        "toZoneId": dest,
        "status": status,
        "distanceKm": distance,
        "speedLimitKmh": 30.0,
    }


def _loader(eid: int, code: str, state=EquipmentState.LOADING):
    return SimpleNamespace(equipment_id=eid, code=code, active=True, current_state=state)


def test_auditor_flags_fabricated_unknown_origin():
    violations = recommendation_constraint_violations(
        [{"candidateId": "c-bad", "loaderId": 24, "originZoneCode": "BANC_A", "waitMinutes": 4.0, "roadIds": []}],
        loader_zones={},
        origin_code="BANC_A",
    )
    assert violations
    assert any("unknown loader" in item or "truck origin" in item for item in violations)


def test_multi_seed_dispatch_metrics_are_reproducible_and_not_equal_split():
    reports = {seed: _dispatch_metrics(seed) for seed in SEEDS}
    replay = _dispatch_metrics(1)
    assert reports[1]["fingerprint"] == replay["fingerprint"]
    assert reports[1]["fingerprint"] != reports[2]["fingerprint"]
    assert reports[1]["fingerprint"] != reports[7]["fingerprint"]
    for report in reports.values():
        assert report["trucks"] == 20
        assert set(report["per_bench"]) <= {"BENCH_NORTH", "BENCH_SOUTH", OPAQUE_BENCH}
        assert OPAQUE_BENCH in report["per_bench"]
        assert report["over_occupancy"], "queues beyond occupancy must remain possible"


def test_optimizer_outcome_bundle_and_zero_constraint_violations():
    truck = SimpleNamespace(equipment_id=1, code="TRK-001")
    assignment = SimpleNamespace(loader_id=21, origin_zone_id=1, destination_zone_id=9)
    loaders = [
        _loader(21, "EXC-A"),
        _loader(22, "EXC-B"),
        _loader(24, "LDR-001"),
        _loader(99, "EXC-DOWN", EquipmentState.STOPPED_MECHANICAL),
    ]
    roads = [
        _open_road("R-A", "BANC_A", "DUMP_N"),
        _open_road("R-B", "BANC_B", "DUMP_N"),
        _open_road("R-CLOSED", "BANC_A", "DUMP_N", status="CLOSED"),
    ]
    loading = {
        "loaders": [
            {"loaderId": 21, "waitingTruckCount": 4, "waitingTrucks": [{"waitingMinutes": 12.0}]},
            {"loaderId": 22, "waitingTruckCount": 1, "waitingTrucks": [{"waitingMinutes": 3.0}]},
            {"loaderId": 24, "waitingTruckCount": 0, "waitingTrucks": []},
        ]
    }
    loader_zones = {21: "BANC_A", 22: "BANC_B"}
    feasible = generate_candidates(
        truck=truck,
        assignment=assignment,
        loaders=loaders,
        roads=roads,
        zone_codes={1: "BANC_A", 2: "BANC_B", 9: "DUMP_N"},
        loading=loading,
        origin_code="BANC_A",
        dest_code="DUMP_N",
        loader_zones=loader_zones,
    )
    feasible_outcome, _ = dispatch_outcome(truck=truck, dest="DUMP_N", candidates=feasible)

    infeasible = generate_candidates(
        truck=truck,
        assignment=assignment,
        loaders=loaders,
        roads=[_open_road("R-X", "BANC_A", "DUMP_N", status="CLOSED")],
        zone_codes={1: "BANC_A", 9: "DUMP_N"},
        loading=loading,
        origin_code="BANC_A",
        dest_code="DUMP_N",
        loader_zones=loader_zones,
    )
    infeasible_outcome, _ = dispatch_outcome(truck=truck, dest="DUMP_N", candidates=infeasible)

    insufficient = generate_candidates(
        truck=truck,
        assignment=assignment,
        loaders=loaders,
        roads=[_open_road("R-NULL", "BANC_A", "DUMP_N", distance=None)],
        zone_codes={1: "BANC_A", 9: "DUMP_N"},
        loading={"loaders": [{"loaderId": 21, "waitingTruckCount": 1, "waitingTrucks": [{}]}]},
        origin_code="BANC_A",
        dest_code="DUMP_N",
        loader_zones={21: "BANC_A"},
    )
    insufficient_outcome, _ = dispatch_outcome(truck=truck, dest="DUMP_N", candidates=insufficient)

    counts = Counter([feasible_outcome, infeasible_outcome, insufficient_outcome])
    assert counts["FEASIBLE"] == 1
    assert counts["NO_FEASIBLE_PLAN"] == 1
    assert counts["INSUFFICIENT_DATA"] == 1

    confirmed = rca_constraints(
        diagnosis_status="CONFIRMED",
        reliable_root_cause=True,
        equipment_id=22,
        equipment_type=EquipmentType.EXCAVATOR,
        supported_hypothesis_ids=["h-confirmed"],
    )
    probable = rca_constraints(
        diagnosis_status="PROBABLE",
        reliable_root_cause=False,
        equipment_id=21,
        equipment_type=EquipmentType.EXCAVATOR,
        supported_hypothesis_ids=["h-probable"],
    )
    hypothesis = rca_constraints(
        diagnosis_status="INCONCLUSIVE",
        reliable_root_cause=False,
        equipment_id=21,
        equipment_type=EquipmentType.EXCAVATOR,
        supported_hypothesis_ids=["h-maybe"],
    )
    assert confirmed.hard_exclude_loader_ids == {22}
    assert probable.hard_exclude_loader_ids == set()
    assert hypothesis.hard_exclude_loader_ids == set()

    trusted = {
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
    }
    composed = execute_selected_engines(
        trusted=trusted,
        optimizer_ids=[OptimizerId.DISPATCH_LOADER],
        objectives=[],
        constraints=[
            ConstraintCode.EXCLUDE_UNAVAILABLE_EQUIPMENT,
            ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK,
        ],
    )
    measured = {int(row["loaderId"]): row.get("waitMinutes") for row in composed if row.get("loaderId") is not None}
    for row in composed:
        if row.get("loaderId") == 22:
            assert row["waitMinutes"] == 3.0
            assert row["pendingCommitmentCount"] == 2
            assert row["projectedPressure"] == 3
            assert "projectedWaitMinutes" in row
    composed = apply_rca_excludes(composed, confirmed.hard_exclude_loader_ids)
    finalized = finalize_recommendations(composed)
    accepted = finalized["displayed"] or [
        row for row in finalized["candidates"] if row.get("candidateId") == finalized.get("recommendedCandidateId")
    ]
    closed = {row["id"] for row in roads if row["status"] == "CLOSED"}
    violations = recommendation_constraint_violations(
        accepted,
        loader_zones=loader_zones,
        origin_code="BANC_A",
        hard_exclude_loader_ids=confirmed.hard_exclude_loader_ids,
        measured_wait=measured,
        closed_road_ids=closed,
        unavailable_loader_ids={99},
    )
    assert violations == []
    assert {row.get("loaderId") for row in accepted} <= set(loader_zones)
    assert 22 not in {row.get("loaderId") for row in accepted}
    assert 24 not in {row.get("loaderId") for row in accepted}
    assert 99 not in {row.get("loaderId") for row in composed}
