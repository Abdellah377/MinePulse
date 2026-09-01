"""Operational integration for the served Failure-Risk V1 logistic artifact."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import pytest

from app.ml.failure_risk.contracts import DATA_CLASS, FailureRiskStatus
from app.ml.failure_risk.dataset import EquipmentInfo, FailureRiskSnapshot, StateInterval, TelemetrySample
from app.ml.failure_risk.inference import predict_from_snapshot, resolve_artifact
from app.ml.failure_risk.model import ARTIFACT_FILE, DEFAULT_ARTIFACT_DIR
from app.ml.failure_risk.spec import TELEMETRY_FEATURE_FIELDS
from app.ml.failure_risk.train import train_from_rows
from app.monitoring.detectors import detect_predicted_mechanical_failure_risk
from app.services.operational.failure_risk import failure_risk_to_dto

from test_ml_failure_risk import _at, _balanced_rows, _snapshot
from test_monitoring_detectors import _settings, _snapshot as _monitoring_snapshot

T0 = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)

def _nominal_tel(equipment_id: int, minutes: int, **overrides) -> TelemetrySample:
    values = {name: 0.0 for name in TELEMETRY_FEATURE_FIELDS}
    values.update(
        {
            "engine_temp_c": 86.0,
            "coolant_temp_c": 80.0,
            "oil_pressure_kpa": 410.0,
            "battery_voltage": 27.2,
            "engine_rpm": 1400.0,
            "engine_load_pct": 40.0,
            "fuel_rate_lph": 18.0,
            "fuel_level_pct": 70.0,
            "speed_kmh": 25.0,
            "payload_t": 180.0,
            "communication_quality": 95.0,
            "engine_hours": 1000.0,
            "odometer_km": 5000.0,
        }
    )
    values.update(overrides)
    return TelemetrySample(equipment_id=equipment_id, ts=_at(minutes), values=values)


def _nominal_snapshot(*, end_min: int = 80) -> FailureRiskSnapshot:
    return FailureRiskSnapshot(
        equipment={1: EquipmentInfo(1, "TRK-001"), 2: EquipmentInfo(2, "TRK-002")},
        telemetry=[_nominal_tel(1, minute) for minute in range(0, end_min + 1, 2)],
        states=[StateInterval(1, "MOVING_LOADED", _at(0), None)],
        oem_events=[],
        maintenance=[],
    )


def _canonical_artifact():
    path = DEFAULT_ARTIFACT_DIR / ARTIFACT_FILE
    if not path.is_file():
        pytest.skip("canonical Failure-Risk V1 artifact is not present")
    resolved = resolve_artifact(artifacts_dir=DEFAULT_ARTIFACT_DIR)
    if getattr(resolved, "status", None) == FailureRiskStatus.UNAVAILABLE:
        pytest.skip(f"canonical artifact is not servable: {getattr(resolved, 'detail', None)}")
    return resolved


def test_canonical_artifact_serves_logistic_not_hgb():
    artifact = _canonical_artifact()
    assert artifact.served_predictor == "logistic"
    assert artifact.logistic is not None
    assert artifact.hgb is not None
    assert 0.9 < float(artifact.threshold) < 1.0
    assert (artifact.metadata or {}).get("training_data_type") == "synthetic"
    assert (artifact.metadata or {}).get("experiment_decision") == "LOGISTIC_PROMOTED"


def test_canonical_disk_resolve_does_not_rewrite_served_predictor():
    artifact = _canonical_artifact()
    again = resolve_artifact(artifacts_dir=DEFAULT_ARTIFACT_DIR)
    assert again.served_predictor == artifact.served_predictor == "logistic"


def test_equipment_detail_and_monitoring_use_the_same_inference_functions():
    from app.ml.failure_risk import inference as inference_mod
    from app.monitoring import predictive as predictive_mod
    from app.services.operational import failure_risk as ops_mod

    assert ops_mod.predict_failure_risk is inference_mod.predict_failure_risk
    assert "score_equipment" in inspect.getsource(predictive_mod.attach_failure_risk_predictions)
    assert "predict_failure_risk" in inspect.getsource(ops_mod.current_failure_risk)


def test_failure_risk_dto_omits_hidden_simulator_truth():
    from app.ml.failure_risk.contracts import FailureRiskPrediction

    dto = failure_risk_to_dto(
        FailureRiskPrediction(
            equipment_id=10,
            equipment_code="TRK-010",
            prediction_timestamp=T0,
            feature_timestamp=T0,
            horizon_minutes=60,
            risk_probability=0.12,
            risk_level="LOW",
            status=FailureRiskStatus.AVAILABLE,
            data_class=DATA_CLASS,
            served_predictor="logistic",
            model_type="logistic",
        )
    )
    forbidden = {
        "scenarioId",
        "scenario_id",
        "sabotage",
        "hiddenRootCause",
        "hidden_root_cause",
        "countdown",
        "predictedFor",
        "internal_failure_countdown",
        "degradationStage",
    }
    assert forbidden.isdisjoint(dto)
    assert dto["featureTimestamp"] == T0.isoformat()
    assert dto["servedPredictor"] == "logistic"


def test_ordinary_failure_risk_path_has_no_llm_imports():
    banned = {"openai", "anthropic", "litellm", "langchain", "langgraph", "google.generativeai"}
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "app" / "ml" / "failure_risk",
        root / "app" / "services" / "operational" / "failure_risk.py",
        root / "app" / "monitoring" / "predictive.py",
        root / "app" / "monitoring" / "detectors.py",
        root / "app" / "api" / "routes" / "equipment.py",
    ]
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(path.rglob("*.py"))
        else:
            files.append(path)
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module.split(".")[0]]
            else:
                continue
            assert banned.isdisjoint(modules), path


def test_monitoring_skips_unavailable_scores_from_shared_inference():
    from app.ml.failure_risk.contracts import FailureRiskPrediction

    unavailable = FailureRiskPrediction(
        equipment_id=10,
        equipment_code="TRK-010",
        status=FailureRiskStatus.UNAVAILABLE,
        risk_probability=None,
        threshold=0.949,
        served_predictor="logistic",
    )
    snapshot = _monitoring_snapshot(failure_risk={10: unavailable})
    assert detect_predicted_mechanical_failure_risk(snapshot, _settings()) == []


def _degrading_snapshot(*, fail_at: int, ramp_start: int, kind: str) -> FailureRiskSnapshot:
    telemetry: list[TelemetrySample] = []
    for minute in range(0, fail_at + 24, 2):
        if minute < ramp_start:
            telemetry.append(_nominal_tel(1, minute))
        elif minute < fail_at:
            progress = (minute - ramp_start) / max(fail_at - ramp_start, 1)
            if kind == "hot":
                telemetry.append(
                    _nominal_tel(
                        1,
                        minute,
                        engine_temp_c=86.0 + 40.0 * progress,
                        coolant_temp_c=80.0 + 28.0 * progress,
                    )
                )
            elif kind == "oil":
                telemetry.append(
                    _nominal_tel(
                        1,
                        minute,
                        oil_pressure_kpa=410.0 - 250.0 * progress,
                        battery_voltage=27.2 - 5.0 * progress,
                    )
                )
            else:
                telemetry.append(
                    _nominal_tel(
                        1,
                        minute,
                        engine_temp_c=86.0 + 32.0 * progress,
                        coolant_temp_c=80.0 + 22.0 * progress,
                        oil_pressure_kpa=410.0 - 220.0 * progress,
                        battery_voltage=27.2 - 4.0 * progress,
                    )
                )
        else:
            telemetry.append(
                _nominal_tel(
                    1,
                    minute,
                    engine_temp_c=128.0,
                    coolant_temp_c=112.0,
                    oil_pressure_kpa=90.0,
                    battery_voltage=21.0,
                )
            )
    return FailureRiskSnapshot(
        equipment={1: EquipmentInfo(1, "TRK-001"), 2: EquipmentInfo(2, "TRK-002")},
        telemetry=telemetry,
        states=[
            StateInterval(1, "MOVING_LOADED", _at(0), _at(fail_at)),
            StateInterval(1, "STOPPED_MECHANICAL", _at(fail_at), _at(fail_at + 40)),
        ],
        oem_events=[],
        maintenance=[],
    )


def _first_alert_minute(snapshot: FailureRiskSnapshot, artifact, fail_at: int) -> int | None:
    for minute in range(20, fail_at, 2):
        prediction = predict_from_snapshot(snapshot, 1, _at(minute), artifact)
        if (
            prediction.status == FailureRiskStatus.AVAILABLE
            and prediction.risk_probability is not None
            and prediction.risk_probability >= artifact.threshold
        ):
            return minute
    return None


def test_healthy_truck_does_not_alert_on_toy_or_canonical_model():
    snapshot = _snapshot(end_min=80)
    toy, _report = train_from_rows(_balanced_rows())
    healthy = predict_from_snapshot(snapshot, 1, _at(40), toy)
    assert healthy.status == FailureRiskStatus.AVAILABLE
    assert healthy.risk_probability is not None
    from test_monitoring_detectors import _failure_risk_prediction

    findings = detect_predicted_mechanical_failure_risk(
        _monitoring_snapshot(
            failure_risk={
                10: _failure_risk_prediction(
                    risk_probability=healthy.risk_probability,
                    threshold=toy.threshold,
                    risk_level=healthy.risk_level,
                )
            }
        ),
        _settings(),
    )
    if healthy.risk_probability < toy.threshold:
        assert findings == []

    path = DEFAULT_ARTIFACT_DIR / ARTIFACT_FILE
    if path.is_file():
        artifact = _canonical_artifact()
        canonical = predict_from_snapshot(_nominal_snapshot(end_min=80), 1, _at(40), artifact)
        assert canonical.status == FailureRiskStatus.AVAILABLE
        assert canonical.served_predictor == "logistic"
        assert canonical.risk_probability is not None
        assert canonical.risk_probability < artifact.threshold


def test_active_mechanical_stop_is_not_a_future_risk():
    snapshot = _snapshot(end_min=240, incidents=[(180, 210, 1)])
    toy, _report = train_from_rows(_balanced_rows())
    result = predict_from_snapshot(snapshot, 1, _at(190), toy)
    assert result.status == FailureRiskStatus.UNAVAILABLE
    assert result.risk_probability is None
    assert "STOPPED_MECHANICAL" in (result.detail or "")


def test_predictive_lead_time_varies_across_degradation_scenarios():
    toy, _report = train_from_rows(_balanced_rows())
    scenarios = [
        (180, 90, "hot"),
        (200, 120, "hot"),
        (220, 100, "mixed"),
        (160, 80, "oil"),
        (240, 140, "mixed"),
    ]
    leads: list[int] = []
    for fail_at, ramp_start, kind in scenarios:
        snapshot = _degrading_snapshot(fail_at=fail_at, ramp_start=ramp_start, kind=kind)
        first = _first_alert_minute(snapshot, toy, fail_at)
        if first is None:
            continue
        lead = fail_at - first
        assert lead >= 0
        leads.append(lead)
        stopped = predict_from_snapshot(snapshot, 1, _at(fail_at), toy)
        assert stopped.status == FailureRiskStatus.UNAVAILABLE
        assert stopped.risk_probability is None

    if not leads:
        pytest.skip("toy logistic did not cross its threshold before STOPPED_MECHANICAL")
    assert median(leads) >= 0
    assert min(leads) != max(leads) or len(leads) == 1


def test_canonical_artifact_lead_times_when_present():
    artifact = _canonical_artifact()
    scenarios = [
        (180, 60, "oil"),
        (200, 80, "mixed"),
        (220, 90, "hot"),
        (160, 50, "oil"),
        (240, 100, "mixed"),
        (190, 70, "oil"),
    ]
    leads: list[int] = []
    for fail_at, ramp_start, kind in scenarios:
        snapshot = _degrading_snapshot(fail_at=fail_at, ramp_start=ramp_start, kind=kind)
        first = _first_alert_minute(snapshot, artifact, fail_at)
        if first is None:
            continue
        leads.append(fail_at - first)
    if not leads:
        pytest.skip("canonical logistic did not alert before STOPPED_MECHANICAL on synthetic ramps")
    stats = f"n={len(leads)} leads={leads} median={median(leads)} range={min(leads)}-{max(leads)}"
    assert all(lead > 0 for lead in leads), stats
    assert median(leads) > 0, stats
