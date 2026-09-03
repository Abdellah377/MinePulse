from collections import Counter

from simulator.config import SimConfig
from simulator.dispatch import assign_fleet, discover_feasible_slots
from simulator.world import SimWorld


def test_pressure_aware_assignment_uses_discovered_loaders() -> None:
    slots = discover_feasible_slots(
        zone_types={
            "PAD_A": "LOADING_BENCH",
            "PAD_B": "LOADING_BENCH",
            "DUMP": "DUMP_AREA",
        },
        zone_capacity={"PAD_A": 3, "PAD_B": 3},
        zone_status={"PAD_A": "ACTIVE", "PAD_B": "ACTIVE"},
        loaders=[("SHV-A1", 1, "PAD_A"), ("SHV-A2", 2, "PAD_A"), ("SHV-B", 3, "PAD_B")],
        roads=[("PAD_A", "DUMP"), ("PAD_B", "DUMP")],
    )
    trucks = [(i, f"TR-{i:02d}") for i in range(1, 21)]
    assigned = assign_fleet(trucks, slots, seed=1)
    world = SimWorld(SimConfig(random_seed=1))
    world.load_trucks(assigned, seed=1, zone_centroids={"DUMP": (-6.66, 32.66), "PAD_A": (-6.68, 32.67), "PAD_B": (-6.67, 32.65)})
    counts = Counter(truck.loader_code for truck in world.trucks.values())
    assert set(counts) == {"SHV-A1", "SHV-A2", "SHV-B"}
    assert all(count > 0 for count in counts.values())
    pad_b = [truck for truck in world.trucks.values() if truck.origin_zone_code == "PAD_B"]
    assert pad_b
    assert all(truck.loader_code == "SHV-B" for truck in pad_b)
    pad_a = [truck for truck in world.trucks.values() if truck.origin_zone_code == "PAD_A"]
    assert {truck.loader_code for truck in pad_a} <= {"SHV-A1", "SHV-A2"}
