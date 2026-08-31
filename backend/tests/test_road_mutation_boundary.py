from pathlib import Path

from app.services.operational import roads as road_service


AI_ROOT = Path(__file__).resolve().parents[1] / "app" / "ai"
MONITORING_ROOT = Path(__file__).resolve().parents[1] / "app" / "monitoring"
COMMAND_REGISTRY = Path(__file__).resolve().parents[1] / "simulator" / "command_registry.py"


def test_ai_and_monitoring_do_not_import_road_mutations():
    forbidden = "app.services.operational.roads"
    for root in (AI_ROOT, MONITORING_ROOT):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert forbidden not in text, path


def test_simulator_close_road_does_not_write_haul_road_status():
    source = COMMAND_REGISTRY.read_text(encoding="utf-8")
    assert "road.closed = True" in source
    assert "HaulRoad" not in source
    assert "app.services.operational.roads" not in source
    assert "status = \"CLOSED\"" not in source
    assert road_service.__doc__ and "Operator-only" in road_service.__doc__
