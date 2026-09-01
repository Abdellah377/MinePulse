from collections import Counter

from simulator.config import SimConfig
from simulator.world import SimWorld


def test_static_loader_assignment_is_balanced() -> None:
    world = SimWorld(SimConfig(random_seed=1))
    rows = [(i, f"TR-{i:02d}") for i in range(1, 21)]
    world.load_trucks(rows, seed=1)
    counts = Counter(truck.loader_code for truck in world.trucks.values())
    assert set(counts) == {"EXC-001", "EXC-002", "EXC-003"}
    assert max(counts.values()) - min(counts.values()) <= 1
    assert counts["EXC-002"] < 10
    banc_b = [truck for truck in world.trucks.values() if truck.origin_zone_code == "BANC_B"]
    assert banc_b
    assert all(truck.loader_code == "EXC-002" for truck in banc_b)
    banc_a = [truck for truck in world.trucks.values() if truck.origin_zone_code == "BANC_A"]
    assert {truck.loader_code for truck in banc_a} <= {"EXC-001", "EXC-003"}
