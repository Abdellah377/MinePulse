from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from app.ai.contracts import Severity, TriggerType
from app.config import Settings
from app.db.enums import AlertSeverity, AlertSource, AlertStatus, EquipmentState, EquipmentType
from app.db.models import Alert, Cycle, Equipment, EquipmentTelemetry, Shift, Site
from app.db.models.telemetry import EquipmentState as EquipmentStateRow
from app.ml.failure_risk.contracts import FailureRiskPrediction, FailureRiskStatus
from app.monitoring.contracts import MonitoringSnapshot
from app.monitoring.detectors import (
    DEFAULT_DETECTORS,
    detect_abnormal_cycle_duration,
    detect_communication_degradation,
    detect_critical_conditions,
    detect_predicted_mechanical_failure_risk,
    detect_production_deviation,
    detect_prolonged_idle_wait,
    detect_unexpected_stops,
)
from app.services.operational.context import OperationalContext
from app.services.operational.equipment import FleetBulkContext

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _settings(**overrides) -> Settings:
    values = {
        "monitoring_enabled": True,
        "monitoring_unexpected_stop_minutes": 2,
        "monitoring_idle_threshold_minutes": 5,
        "monitoring_communication_quality_threshold": 60,
        "monitoring_communication_critical_threshold": 30,
        "monitoring_telemetry_stale_seconds": 120,
        "monitoring_production_deviation_pct": 20,
        "monitoring_cycle_duration_multiplier": 1.5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _snapshot(
    *,
    state: EquipmentState = EquipmentState.MOVING_EMPTY,
    state_minutes: float = 1,
    telemetry: EquipmentTelemetry | None = None,
    alerts: list[Alert] | None = None,
    production: dict | None = None,
    open_maintenance: set[int] | None = None,
    active_cycle: Cycle | None = None,
    average_cycle: float | None = None,
    failure_risk: dict[int, FailureRiskPrediction] | None = None,
    equipment_type: EquipmentType = EquipmentType.HAUL_TRUCK,
) -> MonitoringSnapshot:
    site = Site(site_id=1, code="SITE-A", name="Site A", active=True)
    shift = Shift(
        shift_id=2, site_id=1, name="Jour", shift_date=date(2026, 8, 27),
        start_time=time(6), end_time=time(18),
    )
    context = OperationalContext(
        site=site, shift=shift, sim_now=NOW,
        shift_window_start=NOW - timedelta(hours=6), shift_window_end=NOW + timedelta(hours=6),
    )
    equipment = Equipment(
        equipment_id=10, site_id=1, code="TRK-010", type=equipment_type,
        current_state=state, active=True,
    )
    state_row = EquipmentStateRow(
        state_id=99, equipment_id=10, state=state,
        start_time=NOW - timedelta(minutes=state_minutes), end_time=None,
    )
    fleet = FleetBulkContext(
        state_rows={10: [state_row]},
        telemetry={10: telemetry} if telemetry else {},
        open_maintenance=open_maintenance or set(),
        active_cycles={10: active_cycle} if active_cycle else {},
        avg_cycle_min={10: average_cycle},
    )
    return MonitoringSnapshot(
        context=context,
        equipment=[equipment],
        fleet=fleet,
        production=production or {"hourly": [], "daily": [], "shiftly": []},
        active_alerts=alerts or [],
        failure_risk=failure_risk or {},
    )


def test_unexpected_stop_threshold_boundary_and_no_root_cause_claim():
    findings = detect_unexpected_stops(
        _snapshot(state=EquipmentState.STOPPED_UNDEFINED, state_minutes=2), _settings()
    )
    assert len(findings) == 1
    assert findings[0].trigger_type == TriggerType.EQUIPMENT_ANOMALY
    assert findings[0].value == 2
    assert findings[0].threshold == 2
    assert "cause" not in findings[0].context
    assert detect_unexpected_stops(
        _snapshot(state=EquipmentState.STOPPED_UNDEFINED, state_minutes=1.99), _settings()
    ) == []


def test_prolonged_wait_boundary():
    findings = detect_prolonged_idle_wait(
        _snapshot(state=EquipmentState.WAITING_LOADING, state_minutes=5), _settings()
    )
    assert len(findings) == 1
    assert findings[0].value == 5
    assert findings[0].trigger_type == TriggerType.CONGESTION_RISK


def test_wait_duration_is_consistent_with_operational_detection_time():
    duration_minutes = 8.3
    finding = detect_prolonged_idle_wait(
        _snapshot(
            state=EquipmentState.WAITING_LOADING,
            state_minutes=duration_minutes,
        ),
        _settings(),
    )[0]
    inferred_state_start = finding.detected_at - timedelta(minutes=finding.value)
    assert finding.detected_at == NOW
    assert inferred_state_start == NOW - timedelta(minutes=duration_minutes)
    assert "8.3 min" in finding.reason


def test_communication_measured_zero_is_critical_but_null_is_not_zero():
    measured_zero = EquipmentTelemetry(
        telemetry_id=1, equipment_id=10, ts=NOW,
        communication_quality=Decimal("0"), raw_data={},
    )
    findings = detect_communication_degradation(_snapshot(telemetry=measured_zero), _settings())
    assert len(findings) == 1
    assert findings[0].value == 0
    assert findings[0].severity == Severity.CRITICAL

    unknown = EquipmentTelemetry(
        telemetry_id=2, equipment_id=10, ts=NOW,
        communication_quality=None, raw_data={},
    )
    assert detect_communication_degradation(_snapshot(telemetry=unknown), _settings()) == []


def test_stale_telemetry_and_missing_telemetry_semantics():
    stale = EquipmentTelemetry(
        telemetry_id=1, equipment_id=10, ts=NOW - timedelta(seconds=120),
        communication_quality=None, raw_data={},
    )
    finding = detect_communication_degradation(_snapshot(telemetry=stale), _settings())[0]
    assert finding.metric == "telemetry_age"
    assert finding.value == 120
    # No telemetry on an otherwise live machine is unknown, not fabricated age zero.
    assert detect_communication_degradation(_snapshot(), _settings()) == []


def test_critical_existing_alert_is_reused_and_suppresses_duplicate_stop():
    alert = Alert(
        alert_id=44, created_at=NOW, source=AlertSource.FMS,
        severity=AlertSeverity.CRITICAL, status=AlertStatus.NEW,
        alert_type="MECHANICAL", title="Arrêt critique", description="Arrêt confirmé",
        equipment_id=10, metadata_={},
    )
    snapshot = _snapshot(
        state=EquipmentState.STOPPED_MECHANICAL, state_minutes=10, alerts=[alert]
    )
    findings = detect_critical_conditions(snapshot, _settings())
    assert len(findings) == 1
    assert findings[0].source_alert_id == 44
    assert findings[0].trigger_type == TriggerType.MAINTENANCE_RISK
    assert detect_unexpected_stops(snapshot, _settings()) == []


def test_production_detector_uses_published_hourly_target_and_preserves_missing_data():
    production = {
        "hourly": [
            {"label": "10h", "tonnage": 70.0, "target": 100.0},
            {"label": "11h", "tonnage": 70.0, "target": 100.0},
        ],
        "daily": [], "shiftly": [],
    }
    finding = detect_production_deviation(_snapshot(production=production), _settings())[0]
    assert finding.value == 30
    assert finding.context == {"actualTonnes": 140.0, "targetTonnes": 200.0}

    missing = {"hourly": [{"label": "11h", "tonnage": None, "target": 100}], "daily": [], "shiftly": []}
    assert detect_production_deviation(_snapshot(production=missing), _settings()) == []


def test_abnormal_active_cycle_uses_authoritative_completed_cycle_average():
    cycle = Cycle(
        cycle_id=55, truck_id=10, started_at=NOW - timedelta(minutes=31), status="ACTIVE"
    )
    finding = detect_abnormal_cycle_duration(
        _snapshot(active_cycle=cycle, average_cycle=20), _settings()
    )[0]
    assert finding.value == 31
    assert finding.threshold == 30
    assert finding.context["baselineMinutes"] == 20
    assert detect_abnormal_cycle_duration(
        _snapshot(active_cycle=cycle, average_cycle=None), _settings()
    ) == []


def test_critical_communication_threshold_cannot_exceed_warning_threshold():
    with pytest.raises(ValueError):
        _settings(
            monitoring_communication_quality_threshold=40,
            monitoring_communication_critical_threshold=60,
        )


def _failure_risk_prediction(**overrides) -> FailureRiskPrediction:
    payload = {
        "equipment_id": 10,
        "equipment_code": "TRK-010",
        "prediction_timestamp": NOW,
        "horizon_minutes": 60,
        "risk_probability": 0.82,
        "risk_level": "HIGH",
        "model_version": "failure_risk_v1",
        "model_type": "logistic",
        "threshold": 0.40,
        "status": FailureRiskStatus.AVAILABLE,
        "data_class": "synthetic_prototype",
        "served_predictor": "logistic",
        "top_predictive_signals": ["engine_temp_c", "oil_pressure_kpa"],
    }
    payload.update(overrides)
    return FailureRiskPrediction(**payload)


def test_predicted_failure_risk_fires_at_artifact_threshold_with_predicted_copy():
    findings = detect_predicted_mechanical_failure_risk(
        _snapshot(failure_risk={10: _failure_risk_prediction(threshold=0.31, risk_probability=0.35)}),
        _settings(),
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.detector_id == "predicted-mechanical-failure-risk"
    assert finding.trigger_type == TriggerType.PREDICTED_MECHANICAL_FAILURE_RISK
    assert finding.severity == Severity.WARNING
    assert finding.threshold == 0.31
    assert finding.threshold != 0.80
    assert finding.value == 0.35
    assert finding.metric == "failure_risk_probability"
    assert finding.unit == "probability"
    assert finding.alert_source == AlertSource.PREDICTION
    assert finding.predicted_for is None
    assert finding.deduplication_key == "failure-risk:1:10"
    assert "prédit" in finding.title.casefold() or "prédit" in finding.title
    assert "Risque mécanique prédit" in finding.title
    assert "prédit" in finding.reason
    assert "60" in finding.reason
    assert "will fail" not in finding.reason.casefold()
    assert finding.context["source"] == "FAILURE_RISK_V1"
    assert finding.context["dataClass"] == "synthetic_prototype"
    assert finding.context["modelVersion"] == "failure_risk_v1"
    assert finding.context["horizonMinutes"] == 60


def test_predicted_failure_risk_ignores_scores_below_artifact_threshold():
    assert detect_predicted_mechanical_failure_risk(
        _snapshot(failure_risk={10: _failure_risk_prediction(threshold=0.31, risk_probability=0.30)}),
        _settings(),
    ) == []


def test_predicted_failure_risk_ignores_unavailable_and_insufficient_history():
    unavailable = _snapshot(
        failure_risk={10: _failure_risk_prediction(
            status=FailureRiskStatus.UNAVAILABLE, risk_probability=None, risk_level=None,
        )}
    )
    insufficient = _snapshot(
        failure_risk={10: _failure_risk_prediction(
            status=FailureRiskStatus.INSUFFICIENT_HISTORY, risk_probability=None, risk_level=None,
        )}
    )
    assert detect_predicted_mechanical_failure_risk(unavailable, _settings()) == []
    assert detect_predicted_mechanical_failure_risk(insufficient, _settings()) == []


def test_predicted_failure_risk_skips_equipment_not_in_snapshot_map():
    excavator = _snapshot(equipment_type=EquipmentType.LOADER)
    assert excavator.failure_risk == {}
    assert detect_predicted_mechanical_failure_risk(excavator, _settings()) == []


def test_default_detectors_include_predicted_failure_risk_after_six_deterministic():
    assert detect_predicted_mechanical_failure_risk in DEFAULT_DETECTORS
    assert len(DEFAULT_DETECTORS) == 7
