"""Transport contract/association regressions. No DB, simulator or paid provider required."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import runpy

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.ai.persistence import find_investigations
from app.api.routes import ai
from app.db.database import get_db
from app.main import app
from app.mappers.dto import maintenance_history_for_equipment, site_to_dto
from app.oem import queries


def test_typescript_contract_is_generated_from_current_pydantic_schema():
    root = Path(__file__).resolve().parents[2]
    generator = runpy.run_path(str(root / "backend/scripts/export_ai_types.py"))
    assert (root / "src/lib/api/types/ai.ts").read_text(encoding="utf-8") == generator["generate"]()


def test_association_query_is_scoped_and_reads_durable_history():
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    assert find_investigations(session, site_id=17, source_record_id="alert-42", shift_id=29) == []
    query = session.scalars.call_args.args[0]
    compiled = query.compile(dialect=postgresql.dialect())
    assert 17 in compiled.params.values() and 29 in compiled.params.values()
    assert "alert-42" in compiled.params.values()
    assert "ORDER BY ai_investigations.created_at DESC" in str(compiled)
    assert "LIMIT" in str(compiled)


def test_find_api_does_not_run_graph_and_validates_scope(monkeypatch):
    session = MagicMock()
    finder = MagicMock(return_value=[])
    run = MagicMock(side_effect=AssertionError("GET must not start an investigation"))
    monkeypatch.setattr(ai, "find_investigations", finder)
    monkeypatch.setattr(ai, "run_investigation", run)
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)  # No lifespan: this is a route unit test, not a simulator startup.
        response = client.get("/api/ai/investigations", params={"site_id": 17, "shift_id": 29, "source_record_id": "alert-42"})
        assert response.status_code == 200 and response.json() == []
        finder.assert_called_once_with(session, site_id=17, shift_id=29, source_record_id="alert-42")
        assert client.get("/api/ai/investigations", params={"site_id": 0, "source_record_id": "x"}).status_code == 422
        run.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_reference_identity_and_missing_region_pits_are_not_fabricated():
    dto = site_to_dto(SimpleNamespace(site_id=17, code="REAL-SITE", name="Real site", region=None))
    assert dto["databaseId"] == 17
    assert dto["region"] is None and dto["pits"] == []


def test_unfinished_maintenance_has_no_invented_duration_or_technician():
    session = MagicMock()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    session.scalars.return_value.all.return_value = [SimpleNamespace(maintenance_id=1, start_time=now, actual_end_time=None, expected_end_time=now, metadata_={}, type="inspection", component=None)]
    row = maintenance_history_for_equipment(session, 77)[0]
    assert row["durationH"] is None and row["technician"] is None


def test_tyre_history_preserves_unknown_and_measured_zero(monkeypatch):
    session = MagicMock()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    monkeypatch.setattr(queries, "_equipment", lambda *a, **kw: SimpleNamespace(code="FMS-77", equipment_id=77, type=SimpleNamespace(value="HAUL_TRUCK")))
    monkeypatch.setattr(queries, "parse_range", lambda *a, **kw: (now, now))
    session.execute.return_value.all.return_value = [SimpleNamespace(bucket=now, position="FL", pressure=None, temp=0)]
    result = queries.get_tyre_history(session, "FMS-77", None, None, None, site_id=17)
    assert result["points"][0]["FL_pressure"] is None
    assert result["points"][0]["FL_temp"] == 0


def test_diagnostic_missing_latest_value_is_not_a_working_sensor(monkeypatch):
    session = MagicMock()
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    monkeypatch.setattr(queries, "parse_range", lambda *a, **kw: (now, now))
    session.scalars.return_value.all.return_value = [SimpleNamespace(code="FMS-77", equipment_id=77, type=SimpleNamespace(value="HAUL_TRUCK"))]
    session.execute.return_value.one.return_value = SimpleNamespace(engine_temp_c_min=70, engine_temp_c_avg=75, engine_temp_c_max=80)
    session.scalar.return_value = SimpleNamespace(ts=now, engine_temp_c=None)
    rows = queries.diagnostic_parameters(session, None, None, None, None, params="engine_temp_c", site_id=17)
    assert len(rows) == 1
    assert rows[0]["sensorWorking"] is None and rows[0]["sensorStatus"] is None
    assert rows[0]["thresholdSource"] == "simulation/test"
