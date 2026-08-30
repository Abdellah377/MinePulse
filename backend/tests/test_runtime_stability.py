"""Runtime boundaries, without the live simulator, provider, or operational DB."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.monitoring.predictive import attach_failure_risk_predictions
from app.services.operational.timeline import timeline_for_shift


def test_orm_native_enum_names_match_persisted_schema():
    from app.db.models import Alert, Equipment, AiRecommendation, Zone

    expected = [(Alert, "source", "alert_source"), (Alert, "severity", "alert_severity"),
                (Alert, "status", "alert_status"), (Equipment, "type", "equipment_type"),
                (Equipment, "current_state", "equipment_state"), (Zone, "type", "zone_type"),
                (AiRecommendation, "status", "recommendation_status")]
    for model, column, enum_name in expected:
        assert model.__table__.c[column].type.name == enum_name


def test_corrupt_clock_is_503_not_generic_500_and_health_survives(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.db.database import get_db
    from app.main import app
    from simulator import control

    path = tmp_path / "sim_state.json"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(control, "SIM_STATE_PATH", path)
    monkeypatch.setattr("app.services.operational.clock.get_settings",
                        lambda: SimpleNamespace(operational_clock="simulation"))
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        client = TestClient(app, raise_server_exceptions=False)  # no runtime startup
        response = client.get("/api/equipment/TRK-001/detail")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "OPERATIONAL_CLOCK_UNAVAILABLE"
        assert "JSONDecodeError" not in response.text
        assert client.get("/health").status_code == 200
        assert path.read_text(encoding="utf-8") == ""
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_heartbeat_age_uses_recording_time_not_operational_time(monkeypatch):
    from app.api.routes import simulation

    monkeypatch.setattr(simulation, "get_simulation_service",
                        lambda: SimpleNamespace(running=False, last_error=None))
    monkeypatch.setattr(simulation, "read_heartbeat", lambda: {
        "ts": "2026-01-29T06:00:00+00:00",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })
    status = simulation._heartbeat_status()
    assert status["engine_alive"] is True
    assert 0 <= status["last_heartbeat_age_sec"] < 2


def test_legacy_heartbeat_has_unknown_age(monkeypatch):
    from app.api.routes import simulation

    monkeypatch.setattr(simulation, "get_simulation_service",
                        lambda: SimpleNamespace(running=False, last_error=None))
    monkeypatch.setattr(simulation, "read_heartbeat",
                        lambda: {"ts": "2026-01-29T06:00:00+00:00"})
    assert simulation._heartbeat_status() == {"engine_alive": False, "last_heartbeat_age_sec": None}


def test_equipment_detail_during_clock_reset_publication(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi.testclient import TestClient
    from app.db.database import get_db
    from app.db.enums import EquipmentType
    from app.db.models import Equipment, Site
    from app.main import app
    from simulator import control

    monkeypatch.setattr(control, "SIM_STATE_PATH", tmp_path / "sim_state.json")
    monkeypatch.setattr("app.services.operational.clock.get_settings",
                        lambda: SimpleNamespace(operational_clock="simulation"))
    site = Site(site_id=1, code="TEST", name="Test", active=True)
    monkeypatch.setattr("app.services.operational.context.resolve_site", lambda *_: site)
    monkeypatch.setattr("app.services.operational.context.resolve_shift", lambda *_: None)
    truck = Equipment(equipment_id=10, site_id=1, code="TRK-010", type=EquipmentType.HAUL_TRUCK)
    session = MagicMock()
    session.scalar.return_value = truck
    session.scalars.return_value.all.return_value = []
    monkeypatch.setattr("app.api.routes.equipment.build_fleet_bulk_context",
                        lambda *_: SimpleNamespace(positions={}, telemetry={}, trips={}))
    monkeypatch.setattr("app.api.routes.equipment.enriched_equipment_dto", lambda *_a, **_kw: {"id": truck.code})
    monkeypatch.setattr("app.api.routes.equipment.maintenance_history_for_equipment", lambda *_: [])
    # Unsupported inference output is null, not a fake measured probability.
    from app.ml.failure_risk.contracts import FailureRiskPrediction
    monkeypatch.setattr("app.api.routes.equipment.current_failure_risk", lambda _s, _e, now:
                        FailureRiskPrediction(status="UNAVAILABLE", prediction_timestamp=now))
    stamps = ["2026-01-29T06:00:00+00:00", "2026-01-29T08:00:00+00:00"]
    control.write_control({"status": "PAUSED", "sim_now": stamps[0]})
    stop = Event()

    def reset_style_writer():
        i = 0
        while not stop.is_set():
            control.write_control({"status": "PAUSED", "sim_now": stamps[i % 2]})
            i += 1

    app.dependency_overrides[get_db] = lambda: session
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            writer = pool.submit(reset_style_writer)
            try:
                client = TestClient(app)
                for _ in range(20):
                    response = client.get("/api/equipment/TRK-010/detail")
                    assert response.status_code == 200
                    risk = response.json()["failureRisk"]
                    assert risk["predictionTimestamp"] in stamps
                    assert risk["riskProbability"] is None
            finally:
                stop.set()
                writer.result(timeout=5)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_historical_film_does_not_extend_past_selected_shift():
    start = datetime(2026, 1, 29, 6, tzinfo=timezone.utc)
    end = start + timedelta(hours=8)
    ctx = SimpleNamespace(site_id=1, shift_window_start=start, shift_window_end=end,
                          sim_now=end + timedelta(hours=4))
    session = MagicMock()
    session.scalars.return_value.all.return_value = [SimpleNamespace(
        state_id=1, equipment_id=10, state=EquipmentState.WAITING_LOADING,
        start_time=start + timedelta(hours=7), end_time=None, zone_id=None,
    )]
    segments = timeline_for_shift(session, ctx, {10: "TRK-010"}, {})
    assert len(segments) == 1
    assert segments[0]["end"] == int(end.timestamp() * 1000)
    assert end in session.scalars.call_args.args[0].compile().params.values()


def test_optional_predictive_failure_rolls_back_its_work_not_outer_transaction(monkeypatch):
    from app.db.enums import EquipmentType
    from app.monitoring.contracts import MonitoringSnapshot

    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(text("CREATE TABLE work (id INTEGER PRIMARY KEY)"))
        session.commit()
        session.execute(text("INSERT INTO work VALUES (1)"))
        snapshot = MonitoringSnapshot(
            context=SimpleNamespace(site_id=1, sim_now=datetime.now(timezone.utc)),
            equipment=[SimpleNamespace(equipment_id=10, type=EquipmentType.HAUL_TRUCK)],
            fleet=SimpleNamespace(), production={}, active_alerts=[],
        )

        def broken_score(db, *_args):
            db.execute(text("INSERT INTO work VALUES (2)"))
            raise RuntimeError("optional prediction failed mid-transaction")

        monkeypatch.setattr("app.ml.failure_risk.inference.score_equipment", broken_score)
        result = attach_failure_risk_predictions(session, snapshot)
        assert result.failure_risk == {}
        assert session.scalars(text("SELECT id FROM work")).all() == [1]
        session.execute(text("INSERT INTO work VALUES (3)"))
        session.commit()
        assert session.scalars(text("SELECT id FROM work ORDER BY id")).all() == [1, 3]
    engine.dispose()


@pytest.mark.skipif("not config.getoption('--integration')", reason="isolated PostgreSQL rollback test")
def test_reset_removes_only_derived_prediction_alerts_and_linked_investigations():
    from uuid import uuid4
    from app.db.database import SessionLocal
    from app.db.enums import AlertSeverity, AlertSource, AlertStatus
    from app.db.models import AiInvestigation, Alert, Site
    from simulator.reset_cleanup import clear_simulation_run_data
    from test_simulator_reset_cleanup import _investigation
    from app.ai.contracts import TriggerSource

    with SessionLocal() as session:
        # A unique disposable scope inside ONE rolled-back transaction. Never
        # invoke engine.reset or delete/modify the user's simulation site.
        try:
            now = datetime.now(timezone.utc)
            site = Site(code=f"STABILITY-{uuid4().hex[:8]}", name="isolated test", active=False, created_at=now)
            other = Site(code=f"STABILITY-{uuid4().hex[:8]}", name="other site", active=False, created_at=now)
            session.add_all([site, other])
            session.flush()

            def alert(site_id, monitored):
                return Alert(site_id=site_id, source=AlertSource.PREDICTION,
                             created_at=now, occurred_at=now,
                             severity=AlertSeverity.WARNING, status=AlertStatus.NEW,
                             alert_type="PREDICTED_MECHANICAL_FAILURE_RISK", title="test",
                             metadata_={"monitoring": {"source": "FAILURE_RISK_V1"}} if monitored else {})

            derived, human, unrelated = alert(site.site_id, True), alert(site.site_id, False), alert(other.site_id, True)
            session.add_all([derived, human, unrelated])
            session.flush()
            linked = _investigation(site.site_id, f"alert-{derived.alert_id}", source=TriggerSource.USER_INVESTIGATE)
            session.add(linked)
            session.flush()
            ids = derived.alert_id, human.alert_id, unrelated.alert_id, linked.investigation_id
            counts = clear_simulation_run_data(session, site_code=site.code)
            session.flush()
            session.expire_all()
            assert counts["alerts"] == 1
            assert session.get(Alert, ids[0]) is None
            assert session.get(Alert, ids[1]) is not None
            assert session.get(Alert, ids[2]) is not None
            assert session.get(AiInvestigation, ids[3]) is None
        finally:
            session.rollback()


@pytest.mark.skipif("not config.getoption('--integration')", reason="PostgreSQL transaction semantics")
def test_postgres_query_failure_in_prediction_does_not_poison_caller(monkeypatch):
    from app.db.database import SessionLocal
    from app.db.enums import EquipmentType
    from app.monitoring.contracts import MonitoringSnapshot

    with SessionLocal() as session:
        snapshot = MonitoringSnapshot(
            context=SimpleNamespace(site_id=1, sim_now=datetime.now(timezone.utc)),
            equipment=[SimpleNamespace(equipment_id=10, type=EquipmentType.HAUL_TRUCK)],
            fleet=SimpleNamespace(), production={}, active_alerts=[],
        )
        monkeypatch.setattr("app.ml.failure_risk.inference.score_equipment",
                            lambda db, *_: db.execute(text("SELECT 1 / 0")))
        assert attach_failure_risk_predictions(session, snapshot).failure_risk == {}
        assert session.scalar(text("SELECT 1")) == 1
        session.rollback()
