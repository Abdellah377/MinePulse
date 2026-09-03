"""Data-driven simulator dispatch: discover benches/loaders/roads, no topology strings."""

from collections import Counter
from pathlib import Path

from simulator.dispatch import assign_fleet, discover_feasible_slots


OPAQUE_BENCH = "zone-bea01cb8"


def _catalog(*, shovel_on_opaque: bool = True, opaque_active: bool = True):
    zone_types = {
        "BENCH_NORTH": "LOADING_BENCH",
        "BENCH_SOUTH": "LOADING_BENCH",
        OPAQUE_BENCH: "LOADING_BENCH",
        "DUMP_EAST": "DUMP_AREA",
        "PLANT": "CRUSHER",
    }
    zone_capacity = {"BENCH_NORTH": 3, "BENCH_SOUTH": 3, OPAQUE_BENCH: 4}
    zone_status = {
        "BENCH_NORTH": "ACTIVE",
        "BENCH_SOUTH": "ACTIVE",
        OPAQUE_BENCH: "ACTIVE" if opaque_active else "DISABLED",
    }
    loaders = [
        ("SHV-N", 21, "BENCH_NORTH"),
        ("SHV-S", 22, "BENCH_SOUTH"),
    ]
    if shovel_on_opaque:
        loaders.append(("SHV-C", 23, OPAQUE_BENCH))
    else:
        loaders.append(("SHV-C", 23, None))
    roads = [
        ("BENCH_NORTH", "DUMP_EAST"),
        ("BENCH_SOUTH", "DUMP_EAST"),
        (OPAQUE_BENCH, "DUMP_EAST"),
        (OPAQUE_BENCH, "PLANT"),
        ("BENCH_NORTH", "PLANT"),
    ]
    return zone_types, zone_capacity, zone_status, loaders, roads


def test_opaque_bench_with_shovel_and_roads_receives_trucks():
    zone_types, caps, status, loaders, roads = _catalog(shovel_on_opaque=True)
    slots = discover_feasible_slots(
        zone_types=zone_types,
        zone_capacity=caps,
        zone_status=status,
        loaders=loaders,
        roads=roads,
    )
    assert any(slot.bench_code == OPAQUE_BENCH for slot in slots)
    trucks = [(i, f"TRK-{i:03d}") for i in range(1, 21)]
    assigned = assign_fleet(trucks, slots, seed=7)
    assert any(row.bench_code == OPAQUE_BENCH for row in assigned)


def test_bench_without_shovel_gets_no_assignments():
    zone_types, caps, status, loaders, roads = _catalog(shovel_on_opaque=False)
    slots = discover_feasible_slots(
        zone_types=zone_types,
        zone_capacity=caps,
        zone_status=status,
        loaders=loaders,
        roads=roads,
    )
    assert all(slot.bench_code != OPAQUE_BENCH for slot in slots)
    assigned = assign_fleet([(i, f"T-{i}") for i in range(12)], slots, seed=3)
    assert assigned
    assert all(row.bench_code != OPAQUE_BENCH for row in assigned)


def test_disabled_bench_gets_no_assignments():
    zone_types, caps, status, loaders, roads = _catalog(opaque_active=False)
    slots = discover_feasible_slots(
        zone_types=zone_types,
        zone_capacity=caps,
        zone_status=status,
        loaders=loaders,
        roads=roads,
    )
    assert all(slot.bench_code != OPAQUE_BENCH for slot in slots)


def test_assignments_may_exceed_zone_occupancy():
    slots = discover_feasible_slots(
        zone_types={"PAD": "LOADING_BENCH", "DUMP": "DUMP_AREA"},
        zone_capacity={"PAD": 3},
        zone_status={"PAD": "ACTIVE"},
        loaders=[("SHV-1", 1, "PAD")],
        roads=[("PAD", "DUMP")],
    )
    assigned = assign_fleet([(i, f"T-{i}") for i in range(10)], slots, seed=1)
    assert len(assigned) == 10
    assert all(row.bench_code == "PAD" for row in assigned)


def test_same_seed_reproducible_and_not_forced_equal_split():
    zone_types, caps, status, loaders, roads = _catalog()
    slots = discover_feasible_slots(
        zone_types=zone_types,
        zone_capacity=caps,
        zone_status=status,
        loaders=loaders,
        roads=roads,
    )
    trucks = [(i, f"TRK-{i:03d}") for i in range(1, 21)]
    first = [(row.loader_code, row.bench_code, row.dest_code) for row in assign_fleet(trucks, slots, seed=11)]
    second = [(row.loader_code, row.bench_code, row.dest_code) for row in assign_fleet(trucks, slots, seed=11)]
    other = [(row.loader_code, row.bench_code, row.dest_code) for row in assign_fleet(trucks, slots, seed=99)]
    assert first == second
    assert first != other


def test_dispatch_modules_have_no_banc_c_branch():
    root = Path("simulator")
    files = [root / "dispatch.py", root / "world.py", root / "engine.py"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "BANC_C" not in text
        assert 'endswith("002")' not in text or path.name != "engine.py"
