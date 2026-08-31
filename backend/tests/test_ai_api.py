from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from app.main import app
from app.api.routes import ai
from app.db.database import get_db
from app.ai.contracts import (
    ConfidenceLevel,
    DiagnosisStatus,
    InvestigationConclusion,
    InvestigationResult,
    InvestigationStatus,
    InvestigationTrigger,
    TriggerSource,
    TriggerType,
)
from app.ai.llm.provider import ProviderConfigurationError
from app.ai.persistence import InvestigationPersistenceError


def test_investigation_api_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/ai/investigations" in paths
    assert "/api/ai/investigations/{investigation_id}" in paths
    assert "/api/ai/investigations/{investigation_id}/debug" in paths
    assert "/api/ai/investigations/{investigation_id}/decision" in paths
    assert "/api/ai/investigations/{investigation_id}/decision/follow-up" in paths
    assert "/api/ai/investigations/{investigation_id}/discussion" in paths
    assert "/api/external-context/weather" in paths


def test_missing_migration_returns_storage_error_not_provider_error(monkeypatch):
    class MissingTable(Exception):
        sqlstate = "42P01"
    session = MagicMock()
    monkeypatch.setattr(ai, "find_investigations", MagicMock(side_effect=ProgrammingError("private SQL", {}, MissingTable())))
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).get("/api/ai/investigations", params={"site_id": 1, "source_record_id": "alert-1"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "AI_STORAGE_NOT_READY"
        assert "private SQL" not in response.text
        session.rollback.assert_called_once()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_provider_configuration_and_persistence_failures_remain_distinct(monkeypatch):
    session = MagicMock()
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        trigger = {"site_id": 1, "trigger_type": "PRODUCTION_DEVIATION", "trigger_source": "USER_INVESTIGATE"}
        for error, status, code in [
            (ProviderConfigurationError("secret config"), 503, "AI_PROVIDER_NOT_CONFIGURED"),
            (InvestigationPersistenceError("private SQL"), 500, "AI_PERSISTENCE_FAILED"),
            (RuntimeError("private exception"), 500, "AI_INVESTIGATION_FAILED"),
        ]:
            monkeypatch.setattr(ai, "run_investigation", MagicMock(side_effect=error))
            response = client.post("/api/ai/investigations", json=trigger)
            assert response.status_code == status
            assert response.json()["detail"]["code"] == code
            assert str(error) not in response.text
        assert client.post("/api/ai/investigations", json={"site_id": 1}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_investigation_api_serializes_diagnosis_status(monkeypatch):
    now = datetime(2026, 8, 28, 10, tzinfo=timezone.utc)
    result = InvestigationResult(
        investigation_id=uuid4(),
        trigger=InvestigationTrigger(
            trigger_type=TriggerType.EQUIPMENT_ANOMALY,
            trigger_source=TriggerSource.AUTOMATIC_MONITORING,
            source="monitoring:test",
            site_id=1,
            shift_id=2,
        ),
        conclusion=InvestigationConclusion(
            summary="The available evidence supports the following as the best current explanation: lubrication degradation.",
            diagnosis_status=DiagnosisStatus.PROBABLE,
            root_cause="lubrication degradation",
            reliable_root_cause=False,
            confidence=ConfidenceLevel.MEDIUM,
        ),
        max_iterations=3,
        status=InvestigationStatus.COMPLETED_WITH_UNCERTAINTY,
        started_at=now,
        completed_at=now,
        graph_version="1.3.0",
        provider="mock",
        model="mock",
    )
    session = MagicMock()
    app.dependency_overrides[get_db] = lambda: session
    monkeypatch.setattr(ai, "run_investigation", MagicMock(return_value=result))
    try:
        response = TestClient(app).post(
            "/api/ai/investigations",
            json={
                "site_id": 1,
                "trigger_type": "EQUIPMENT_ANOMALY",
                "trigger_source": "AUTOMATIC_MONITORING",
            },
        )
        assert response.status_code == 200
        payload = response.json()["conclusion"]
        assert payload["diagnosis_status"] == "PROBABLE"
        assert payload["reliable_root_cause"] is False
        assert payload["root_cause"] == "lubrication degradation"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_debug_endpoint_forbidden_when_disabled(monkeypatch):
    monkeypatch.setattr(ai, "get_settings", lambda: type("S", (), {"ai_debug_mode": False})())
    session = MagicMock()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).get(f"/api/ai/investigations/{uuid4()}/debug")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "AI_DEBUG_DISABLED"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_debug_endpoint_returns_trace_when_enabled(monkeypatch):
    monkeypatch.setattr(ai, "get_settings", lambda: type("S", (), {"ai_debug_mode": True})())
    row = MagicMock()
    row.debug_trace = {"investigation_id": "x", "events": [], "stop_reason": "PROBABLE_CAUSE"}
    monkeypatch.setattr(ai, "get_investigation", lambda session, investigation_id: row)
    session = MagicMock()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).get(f"/api/ai/investigations/{uuid4()}/debug")
        assert response.status_code == 200
        assert response.json()["stop_reason"] == "PROBABLE_CAUSE"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_debug_endpoint_missing_trace_is_not_found(monkeypatch):
    monkeypatch.setattr(ai, "get_settings", lambda: type("S", (), {"ai_debug_mode": True})())
    monkeypatch.setattr(ai, "get_investigation", lambda session, investigation_id: None)
    session = MagicMock()
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).get(f"/api/ai/investigations/{uuid4()}/debug")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
