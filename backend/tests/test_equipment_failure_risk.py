"""Current Failure-Risk on equipment detail. No DB, joblib, or simulator required."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.deps import operational_context
from app.db.database import get_db
from app.db.enums import EquipmentType
from app.db.models import Equipment
from app.main import app
from app.ml.failure_risk.contracts import DATA_CLASS, FailureRiskPrediction, FailureRiskStatus
from app.services.operational.failure_risk import current_failure_risk, failure_risk_to_dto

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _truck(**overrides) -> Equipment:
    values = dict(
        equipment_id=10,
        site_id=1,
        code="TRK-010",
        type=EquipmentType.HAUL_TRUCK,
        active=True,
    )
    values.update(overrides)
    return Equipment(**values)


def test_supported_truck_preserves_probability_horizon_and_prototype_metadata(monkeypatch):
    captured = {}

    def fake_predict(session, equipment_id, prediction_time, **kwargs):
        captured["equipment_id"] = equipment_id
        captured["prediction_time"] = prediction_time
        captured["site_id"] = kwargs["site_id"]
        return FailureRiskPrediction(
            equipment_id=equipment_id,
            equipment_code="TRK-010",
            prediction_timestamp=prediction_time,
            horizon_minutes=60,
            risk_probability=0.74,
            risk_level="HIGH",
            model_version="failure_risk_v1",
            model_type="logistic",
            served_predictor="logistic",
            threshold=0.41,
            status=FailureRiskStatus.AVAILABLE,
            data_class=DATA_CLASS,
            top_predictive_signals=["engine_temp_c"],
        )

    monkeypatch.setattr(
        "app.services.operational.failure_risk.predict_failure_risk",
        fake_predict,
    )
    prediction = current_failure_risk(object(), _truck(), NOW)
    assert captured["equipment_id"] == 10
    assert captured["prediction_time"] == NOW
    assert captured["site_id"] == 1
    dto = failure_risk_to_dto(prediction)
    assert dto["riskProbability"] == 0.74
    assert dto["horizonMinutes"] == 60
    assert dto["riskLevel"] == "HIGH"
    assert dto["status"] == "AVAILABLE"
    assert dto["dataClass"] == "synthetic_prototype"
    assert dto["modelType"] == "logistic"
    assert dto["servedPredictor"] == "logistic"
    assert dto["featureTimestamp"] is None
    assert "predictedFor" not in dto
    assert "scenarioId" not in dto
    assert "hiddenRootCause" not in dto
    assert dto["predictionTimestamp"] == NOW.isoformat()


def test_insufficient_history_and_unavailable_do_not_fabricate_probability(monkeypatch):
    monkeypatch.setattr(
        "app.services.operational.failure_risk.predict_failure_risk",
        lambda *_a, **_k: FailureRiskPrediction(
            equipment_id=10,
            status=FailureRiskStatus.INSUFFICIENT_HISTORY,
            risk_probability=None,
            risk_level=None,
        ),
    )
    insufficient = failure_risk_to_dto(current_failure_risk(object(), _truck(), NOW))
    assert insufficient["status"] == "INSUFFICIENT_HISTORY"
    assert insufficient["riskProbability"] is None

    monkeypatch.setattr(
        "app.services.operational.failure_risk.predict_failure_risk",
        lambda *_a, **_k: FailureRiskPrediction(
            equipment_id=10,
            status=FailureRiskStatus.UNAVAILABLE,
            risk_probability=None,
            detail="Model artifact is missing.",
        ),
    )
    missing = failure_risk_to_dto(current_failure_risk(object(), _truck(), NOW))
    assert missing["status"] == "UNAVAILABLE"
    assert missing["riskProbability"] is None
    assert missing["detail"] == "Model artifact is missing."


def test_unsupported_equipment_does_not_call_inference(monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.services.operational.failure_risk.predict_failure_risk",
        lambda *_a, **_k: called.append(1) or (_ for _ in ()).throw(AssertionError("should not score")),
    )
    loader = _truck(equipment_id=20, code="LDR-020", type=EquipmentType.LOADER)
    dto = failure_risk_to_dto(current_failure_risk(object(), loader, NOW))
    assert called == []
    assert dto["status"] == "UNAVAILABLE"
    assert dto["riskProbability"] is None
    assert dto["riskProbability"] != 0
    assert "haul truck" in dto["detail"].casefold()


def test_inference_exception_returns_unavailable_not_crash(monkeypatch):
    monkeypatch.setattr(
        "app.services.operational.failure_risk.predict_failure_risk",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("scoring failed")),
    )
    dto = failure_risk_to_dto(current_failure_risk(object(), _truck(), NOW))
    assert dto["status"] == "UNAVAILABLE"
    assert dto["riskProbability"] is None


def test_equipment_detail_includes_current_failure_risk(monkeypatch):
    truck = _truck()
    ctx = SimpleNamespace(site_id=1, site_code="SITE-A", sim_now=NOW)
    session = MagicMock()
    session.scalar.return_value = truck
    session.scalars.return_value.all.return_value = []
    monkeypatch.setattr(
        "app.api.routes.equipment.build_fleet_bulk_context",
        lambda *_a, **_k: SimpleNamespace(positions={}, telemetry={}, trips={}),
    )
    monkeypatch.setattr(
        "app.api.routes.equipment.enriched_equipment_dto",
        lambda *_a, **_k: {"id": "TRK-010", "code": "TRK-010"},
    )
    monkeypatch.setattr(
        "app.api.routes.equipment.maintenance_history_for_equipment",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "app.api.routes.equipment.current_failure_risk",
        lambda *_a, **_k: FailureRiskPrediction(
            equipment_id=10,
            equipment_code="TRK-010",
            prediction_timestamp=NOW,
            horizon_minutes=60,
            risk_probability=0.74,
            risk_level="HIGH",
            status=FailureRiskStatus.AVAILABLE,
            data_class=DATA_CLASS,
        ),
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[operational_context] = lambda: ctx
    try:
        response = TestClient(app).get("/api/equipment/TRK-010/detail")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(operational_context, None)
    assert response.status_code == 200
    body = response.json()
    assert "failureRisk" in body
    assert body["failureRisk"]["riskProbability"] == 0.74
    assert body["failureRisk"]["horizonMinutes"] == 60
    assert "predictedFor" not in body["failureRisk"]
    assert "predicted_for" not in body["failureRisk"]


def test_operational_failure_risk_module_has_no_simulator_imports():
    root = Path(__file__).resolve().parents[1] / "app"
    paths = [
        root / "services" / "operational" / "failure_risk.py",
        root / "api" / "routes" / "equipment.py",
        root / "ml" / "failure_risk",
    ]
    violations = []
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(path.rglob("*.py"))
        else:
            files.append(path)
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            imported = ([module] if module else []) + names
            if any(name == "simulator" or (name and name.startswith("simulator.")) for name in imported):
                violations.append(str(path))
    assert violations == []
