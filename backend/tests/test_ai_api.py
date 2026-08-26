from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError
from unittest.mock import MagicMock

from app.api.routes import ai
from app.db.database import get_db
from app.ai.llm.provider import ProviderConfigurationError
from app.ai.persistence import InvestigationPersistenceError


def test_investigation_api_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/ai/investigations" in paths
    assert "/api/ai/investigations/{investigation_id}" in paths


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
