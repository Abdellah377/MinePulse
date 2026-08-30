"""Batch generate-cycles performance path: semantics preserved, no GPU, no ML leak."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import Polygon

from app.db.enums import EquipmentState
from app.db.models.telemetry import EquipmentState as EquipmentStateRow
from simulator.cli import cmd_generate_cycles
from simulator.config import SimConfig
from simulator.engine import SimulationEngine
from simulator.geometry import ZoneGeom, resolve_zone_id, resolve_zone_id_from_geom
from simulator.transition_service import _close_open_interval
from simulator.world_model import SimulationWorld


NOW = datetime(2026, 1, 29, 6, 0, tzinfo=timezone.utc)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _zone(code: str, zone_id: int, minx: float, miny: float, maxx: float, maxy: float) -> ZoneGeom:
    poly = Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)])
    c = poly.centroid
    return ZoneGeom(zone_id=zone_id, code=code, polygon=poly, centroid=(float(c.x), float(c.y)))


def test_generate_cycles_enables_batch_generation_not_gpu():
    source = inspect.getsource(cmd_generate_cycles)
    assert "cfg.batch_generation = True" in source
    assert "cfg.commit_every_ticks = 25" in source
    assert "cfg.persist_control_every_ticks = 50" in source
    assert 'engine.world.mode = "MANUAL"' in source
    assert "cupy" not in source
    assert "torch" not in source
    assert "cuda" not in source.lower()


def test_boot_loads_static_lookups_in_stable_order():
    boot = inspect.getsource(SimulationEngine._boot)
    assert "order_by(Equipment.equipment_id, Equipment.code)" in boot
    from simulator.geometry import load_zones, load_roads

    assert "order_by(Zone.code)" in inspect.getsource(load_zones)
    assert "order_by(HaulRoad.code)" in inspect.getsource(load_roads)
    cfg = SimConfig(random_seed=42)
    assert cfg.batch_generation is False
    assert cfg.commit_every_ticks == 1
    assert cfg.persist_control_every_ticks == 1


def test_high_volume_writes_are_batched_not_orm_add():
    assert "_pending_positions.append" in inspect.getsource(SimulationEngine._write_position)
    assert "session.add" not in inspect.getsource(SimulationEngine._write_position)
    assert "_pending_telemetry.append" in inspect.getsource(SimulationEngine._write_telemetry)
    assert "_pending_tyres.append" in inspect.getsource(SimulationEngine._write_tyres)
    assert "insert(EquipmentPosition)" in inspect.getsource(SimulationEngine._flush_telemetry_batch)
    assert "insert(EquipmentTelemetry)" in inspect.getsource(SimulationEngine._flush_telemetry_batch)


def test_pause_commits_deferred_batch_before_control_persist():
    source = inspect.getsource(SimulationEngine.pause)
    assert "_commit_pending" in source
    # tick is now the serialized public boundary; batching remains in _tick.
    assert "command_transaction" in inspect.getsource(SimulationEngine.tick)
    source = inspect.getsource(SimulationEngine._tick)
    assert "batch_generation" in source
    assert "write_heartbeat" in source
    assert "if not self.cfg.batch_generation:" in source
    persist_source = inspect.getsource(SimulationEngine._end_tick_persist)
    assert "commit_every_ticks" in persist_source
    assert "_flush_telemetry_batch" in persist_source


def test_in_memory_zone_lookup_skips_moving_trucks():
    zones = {"A": _zone("A", 11, 0, 0, 1, 1)}
    assert resolve_zone_id_from_geom(zones, 0.5, 0.5, moving=True) is None
    assert resolve_zone_id(None, 1, 0.5, 0.5, moving=True, zones=zones) is None


def test_in_memory_zone_lookup_matches_containing_polygon():
    zones = {
        "A": _zone("A", 11, 0, 0, 1, 1),
        "B": _zone("B", 22, 2, 2, 3, 3),
    }
    assert resolve_zone_id_from_geom(zones, 0.5, 0.5, moving=False) == 11
    assert resolve_zone_id_from_geom(zones, 2.5, 2.5, moving=False) == 22
    assert resolve_zone_id_from_geom(zones, 10.0, 10.0, moving=False) is None
    assert resolve_zone_id(None, 1, 2.5, 2.5, moving=False, zones=zones) == 22


def test_close_open_interval_uses_orm_row_without_session_get():
    row = EquipmentStateRow(
        equipment_id=7,
        state=EquipmentState.LOADING,
        start_time=NOW,
        reason_confirmed=True,
    )
    open_states = {"CAM-001": row}

    def forbidden_get(*_args, **_kwargs):
        raise AssertionError("closing an in-session state row must not query the database")

    session = SimpleNamespace(get=forbidden_get)
    later = NOW + timedelta(minutes=4)
    _close_open_interval(session, open_states, "CAM-001", later)
    assert row.end_time == later
    assert row.duration_sec == 240
    assert "CAM-001" not in open_states


def test_batch_world_skips_event_log_disk_writes(tmp_path, monkeypatch):
    from simulator import world_model as world_model_mod

    writes: list[str] = []

    def capture_append(**kwargs):
        writes.append(kwargs["message"])

    monkeypatch.setattr(world_model_mod, "append_event_log", capture_append)
    cfg = SimConfig(random_seed=1)
    cfg.batch_generation = True
    world = SimulationWorld(cfg)
    world.log_sim(NOW, "queue increased", "ZONE", "BANC_A")
    assert writes == []
    world.log_test(NOW, "reset", "SYSTEM", None)
    assert writes == ["reset"]


def test_simulator_has_no_gpu_libraries():
    forbidden = {"cupy", "torch", "tensorflow", "pycuda"}
    found: list[str] = []
    for path in (BACKEND_ROOT / "simulator").rglob("*.py"):
        for module in _imports(path):
            root = module.split(".", 1)[0]
            if root in forbidden:
                found.append(f"{path.name}:{module}")
    assert found == []


def test_ml_ai_monitoring_do_not_import_simulator():
    roots = [
        BACKEND_ROOT / "app" / "ml",
        BACKEND_ROOT / "app" / "ai",
        BACKEND_ROOT / "app" / "monitoring",
    ]
    violations = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            for module in _imports(path):
                if module == "simulator" or module.startswith("simulator."):
                    violations.append(f"{path}:{module}")
    assert violations == []
