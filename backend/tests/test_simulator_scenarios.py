from datetime import datetime, timezone

from simulator.loaders import LoaderRuntime
from simulator.scenarios import apply_scenarios
from simulator.world_model import SimulationWorld
from simulator.config import SimConfig


def _world_with_loader():
    world = SimulationWorld(SimConfig(random_seed=1))
    world.loaders["EXC-002"] = LoaderRuntime(code="EXC-002", equipment_id=22, zone_code="PAD")
    return world


def test_exc_breakdown_stops_loader_service():
    world = _world_with_loader()
    sim_now = datetime(2026, 1, 29, 6, 31, tzinfo=timezone.utc)
    started = apply_scenarios(world, sim_now, "exc_breakdown")
    assert started == ["exc_breakdown"]
    loader = world.loaders["EXC-002"]
    assert loader.mechanical_breakdown is True
    assert loader.effective_capacity() == 0.0
    assert "EXC-002" in world.excavators_down


def test_exc_breakdown_recovery_restores_loader_service():
    world = _world_with_loader()
    start = datetime(2026, 1, 29, 6, 31, tzinfo=timezone.utc)
    apply_scenarios(world, start, "exc_breakdown")
    assert world.loaders["EXC-002"].effective_capacity() == 0.0
    recover = datetime(2026, 1, 29, 7, 15, tzinfo=timezone.utc)
    apply_scenarios(world, recover, "exc_breakdown")
    loader = world.loaders["EXC-002"]
    assert loader.mechanical_breakdown is False
    assert loader.effective_capacity() > 0
    assert "EXC-002" not in world.excavators_down
