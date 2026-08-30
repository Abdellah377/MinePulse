"""Small deterministic detector set over canonical operational service outputs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from statistics import mean

from app.ai.contracts import Severity, TriggerType
from app.config import Settings
from app.db.enums import AlertSeverity, AlertSource, EquipmentState
from app.ml.failure_risk.contracts import DATA_CLASS, FailureRiskStatus
from app.monitoring.contracts import MonitoringCandidate, MonitoringSnapshot
from app.monitoring.predictive import FAILURE_RISK_SOURCE

Detector = Callable[[MonitoringSnapshot, Settings], list[MonitoringCandidate]]

_WAIT_IDLE_STATES = {
    EquipmentState.WAITING_LOADING,
    EquipmentState.WAITING_DUMPING,
    EquipmentState.STOPPED_OPERATIONAL,
}
_UNEXPECTED_STOP_STATES = {
    EquipmentState.STOPPED_MECHANICAL,
    EquipmentState.STOPPED_UNDEFINED,
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _minutes_between(start: datetime, end: datetime) -> float:
    return max(0.0, (_utc(end) - _utc(start)).total_seconds() / 60.0)


def _current_state_row(snapshot: MonitoringSnapshot, equipment_id: int):
    rows = snapshot.fleet.state_rows.get(equipment_id, [])
    now = _utc(snapshot.context.sim_now)
    current = [
        row for row in rows
        if _utc(row.start_time) <= now and (row.end_time is None or _utc(row.end_time) > now)
    ]
    return max(current, key=lambda row: row.start_time, default=None)


def _severity_for_ratio(value: float, threshold: float) -> Severity:
    return Severity.CRITICAL if value >= threshold * 2 else Severity.WARNING


def detect_unexpected_stops(snapshot: MonitoringSnapshot, settings: Settings) -> list[MonitoringCandidate]:
    candidates: list[MonitoringCandidate] = []
    critical_equipment = {
        alert.equipment_id
        for alert in snapshot.active_alerts
        if alert.equipment_id is not None and alert.severity == AlertSeverity.CRITICAL
    }
    for equipment in snapshot.equipment:
        if equipment.current_state not in _UNEXPECTED_STOP_STATES:
            continue
        # An authoritative critical alert or open maintenance is handled by the
        # critical-condition detector, preventing two investigations for one symptom.
        if equipment.equipment_id in critical_equipment or equipment.equipment_id in snapshot.fleet.open_maintenance:
            continue
        row = _current_state_row(snapshot, equipment.equipment_id)
        if row is None:
            continue
        duration = _minutes_between(row.start_time, snapshot.context.sim_now)
        threshold = settings.monitoring_unexpected_stop_minutes
        if duration < threshold:
            continue
        candidates.append(MonitoringCandidate(
            detector_id="unexpected-equipment-stop",
            trigger_type=TriggerType.EQUIPMENT_ANOMALY,
            site_id=snapshot.context.site_id,
            shift_id=snapshot.context.shift_id,
            equipment_id=equipment.equipment_id,
            zone_id=row.zone_id,
            detected_at=snapshot.context.sim_now,
            severity=_severity_for_ratio(duration, threshold),
            title=f"Arrêt inattendu — {equipment.code}",
            reason=f"{equipment.code} est dans l'état {equipment.current_state.value} depuis {duration:.1f} min.",
            metric="current_stop_duration",
            value=round(duration, 1),
            threshold=threshold,
            unit="min",
            deduplication_key=f"unexpected-stop:{snapshot.context.site_id}:{equipment.equipment_id}",
            context={"equipmentCode": equipment.code, "observedState": equipment.current_state.value},
        ))
    return candidates


def detect_prolonged_idle_wait(snapshot: MonitoringSnapshot, settings: Settings) -> list[MonitoringCandidate]:
    candidates: list[MonitoringCandidate] = []
    for equipment in snapshot.equipment:
        if equipment.current_state not in _WAIT_IDLE_STATES:
            continue
        row = _current_state_row(snapshot, equipment.equipment_id)
        if row is None:
            continue
        duration = _minutes_between(row.start_time, snapshot.context.sim_now)
        threshold = settings.monitoring_idle_threshold_minutes
        if duration < threshold:
            continue
        candidates.append(MonitoringCandidate(
            detector_id="prolonged-idle-wait",
            trigger_type=TriggerType.CONGESTION_RISK,
            site_id=snapshot.context.site_id,
            shift_id=snapshot.context.shift_id,
            equipment_id=equipment.equipment_id,
            zone_id=row.zone_id,
            detected_at=snapshot.context.sim_now,
            severity=_severity_for_ratio(duration, threshold),
            title=f"Attente prolongée — {equipment.code}",
            reason=f"{equipment.code} reste dans l'état {equipment.current_state.value} depuis {duration:.1f} min.",
            metric="current_wait_or_idle_duration",
            value=round(duration, 1),
            threshold=threshold,
            unit="min",
            deduplication_key=f"idle-wait:{snapshot.context.site_id}:{equipment.equipment_id}:{equipment.current_state.value}",
            context={"equipmentCode": equipment.code, "observedState": equipment.current_state.value},
        ))
    return candidates


def detect_communication_degradation(snapshot: MonitoringSnapshot, settings: Settings) -> list[MonitoringCandidate]:
    candidates: list[MonitoringCandidate] = []
    now = snapshot.context.sim_now
    for equipment in snapshot.equipment:
        telemetry = snapshot.fleet.telemetry.get(equipment.equipment_id)
        quality = float(telemetry.communication_quality) if telemetry and telemetry.communication_quality is not None else None
        age_seconds = max(0.0, (_utc(now) - _utc(telemetry.ts)).total_seconds()) if telemetry else None
        reason: str | None = None
        metric: str | None = None
        value = None
        threshold = None
        unit: str | None = None
        severity = Severity.WARNING
        condition = ""
        if equipment.current_state == EquipmentState.NO_DATA:
            reason = f"{equipment.code} signale une perte de données opérationnelles."
            metric, value, threshold, unit = "telemetry_availability", None, None, None
            severity, condition = Severity.CRITICAL, "no-data"
        elif age_seconds is not None and age_seconds >= settings.monitoring_telemetry_stale_seconds:
            reason = f"La dernière télémétrie de {equipment.code} date de {age_seconds:.0f} s."
            metric, value, threshold, unit = (
                "telemetry_age", round(age_seconds, 1), settings.monitoring_telemetry_stale_seconds, "s"
            )
            severity = Severity.CRITICAL if age_seconds >= settings.monitoring_telemetry_stale_seconds * 2 else Severity.WARNING
            condition = "stale"
        elif quality is not None and quality <= settings.monitoring_communication_quality_threshold:
            reason = f"La qualité de communication mesurée pour {equipment.code} est de {quality:.1f} %."
            metric, value, threshold, unit = (
                "communication_quality", quality, settings.monitoring_communication_quality_threshold, "%"
            )
            severity = Severity.CRITICAL if quality <= settings.monitoring_communication_critical_threshold else Severity.WARNING
            condition = "quality"
        if reason is None:
            continue
        candidates.append(MonitoringCandidate(
            detector_id="communication-degradation",
            trigger_type=TriggerType.CONNECTIVITY_ISSUE,
            site_id=snapshot.context.site_id,
            shift_id=snapshot.context.shift_id,
            equipment_id=equipment.equipment_id,
            detected_at=now,
            severity=severity,
            title=f"Communication dégradée — {equipment.code}",
            reason=reason,
            metric=metric,
            value=value,
            threshold=threshold,
            unit=unit,
            deduplication_key=f"communication:{snapshot.context.site_id}:{equipment.equipment_id}:{condition}",
            context={"equipmentCode": equipment.code},
        ))
    return candidates


def detect_critical_conditions(snapshot: MonitoringSnapshot, settings: Settings) -> list[MonitoringCandidate]:
    del settings
    candidates: list[MonitoringCandidate] = []
    alerted_equipment: set[int] = set()
    for alert in snapshot.active_alerts:
        if alert.severity != AlertSeverity.CRITICAL or alert.source in {AlertSource.RULE, AlertSource.AI}:
            continue
        alert_text = f"{alert.alert_type} {alert.title}".casefold()
        if any(token in alert_text for token in ("communication", "connectivity", "signal")):
            trigger_type = TriggerType.CONNECTIVITY_ISSUE
        elif any(token in alert_text for token in ("production", "tonnage")):
            trigger_type = TriggerType.PRODUCTION_DEVIATION
        else:
            trigger_type = TriggerType.MAINTENANCE_RISK
        if alert.equipment_id is not None:
            alerted_equipment.add(alert.equipment_id)
        candidates.append(MonitoringCandidate(
            detector_id="critical-oem-maintenance-condition",
            trigger_type=trigger_type,
            site_id=snapshot.context.site_id,
            shift_id=snapshot.context.shift_id,
            equipment_id=alert.equipment_id,
            zone_id=alert.zone_id,
            detected_at=snapshot.context.sim_now,
            severity=Severity.CRITICAL,
            title=alert.title,
            reason=f"Alerte opérationnelle critique active : {alert.description or alert.title}",
            metric="active_critical_alert",
            value=alert.alert_type,
            threshold=None,
            deduplication_key=f"critical-alert:{alert.alert_id}",
            source_alert_id=alert.alert_id,
            context={"alertType": alert.alert_type, "alertSource": alert.source.value},
        ))
    equipment_by_id = {equipment.equipment_id: equipment for equipment in snapshot.equipment}
    for equipment_id in snapshot.fleet.open_maintenance - alerted_equipment:
        equipment = equipment_by_id.get(equipment_id)
        if equipment is None:
            continue
        candidates.append(MonitoringCandidate(
            detector_id="critical-oem-maintenance-condition",
            trigger_type=TriggerType.MAINTENANCE_RISK,
            site_id=snapshot.context.site_id,
            shift_id=snapshot.context.shift_id,
            equipment_id=equipment_id,
            detected_at=snapshot.context.sim_now,
            severity=Severity.WARNING,
            title=f"Condition maintenance active — {equipment.code}",
            reason=f"{equipment.code} possède un événement de maintenance ouvert.",
            metric="open_maintenance_event",
            value=True,
            threshold=None,
            deduplication_key=f"open-maintenance:{snapshot.context.site_id}:{equipment_id}",
            context={"equipmentCode": equipment.code},
        ))
    return candidates


def detect_production_deviation(snapshot: MonitoringSnapshot, settings: Settings) -> list[MonitoringCandidate]:
    hourly = snapshot.production.get("hourly", [])
    actuals = [float(row["tonnage"]) for row in hourly if row.get("tonnage") is not None]
    targets = [float(row["target"]) for row in hourly if row.get("target") is not None and float(row["target"]) > 0]
    # Absence of a row is unknown, not measured zero.
    if not actuals or len(actuals) != len(targets):
        return []
    actual, target = sum(actuals), sum(targets)
    if target <= 0:
        return []
    deviation_pct = ((target - actual) / target) * 100.0
    threshold = settings.monitoring_production_deviation_pct
    if deviation_pct < threshold:
        return []
    return [MonitoringCandidate(
        detector_id="production-deviation",
        trigger_type=TriggerType.PRODUCTION_DEVIATION,
        site_id=snapshot.context.site_id,
        shift_id=snapshot.context.shift_id,
        detected_at=snapshot.context.sim_now,
        severity=_severity_for_ratio(deviation_pct, threshold),
        title="Écart de production détecté",
        reason=f"La production horaire cumulée est inférieure de {deviation_pct:.1f} % à la cible publiée.",
        metric="hourly_production_deviation",
        value=round(deviation_pct, 1),
        threshold=threshold,
        unit="%",
        deduplication_key=f"production-deviation:{snapshot.context.site_id}:{snapshot.context.shift_id or 'no-shift'}",
        context={"actualTonnes": round(actual, 1), "targetTonnes": round(target, 1)},
    )]


def detect_abnormal_cycle_duration(snapshot: MonitoringSnapshot, settings: Settings) -> list[MonitoringCandidate]:
    candidates: list[MonitoringCandidate] = []
    now = snapshot.context.sim_now
    equipment_by_id = {equipment.equipment_id: equipment for equipment in snapshot.equipment}
    valid_baselines = [value for value in snapshot.fleet.avg_cycle_min.values() if value is not None and value > 0]
    fleet_baseline = mean(valid_baselines) if valid_baselines else None
    for equipment_id, cycle in snapshot.fleet.active_cycles.items():
        baseline = snapshot.fleet.avg_cycle_min.get(equipment_id) or fleet_baseline
        if baseline is None or baseline <= 0:
            continue
        elapsed = _minutes_between(cycle.started_at, now)
        threshold = baseline * settings.monitoring_cycle_duration_multiplier
        if elapsed < threshold:
            continue
        equipment = equipment_by_id.get(equipment_id)
        if equipment is None:
            continue
        candidates.append(MonitoringCandidate(
            detector_id="abnormal-cycle-duration",
            trigger_type=TriggerType.CONGESTION_RISK,
            site_id=snapshot.context.site_id,
            shift_id=snapshot.context.shift_id,
            equipment_id=equipment_id,
            detected_at=now,
            severity=_severity_for_ratio(elapsed, threshold),
            title=f"Cycle anormalement long — {equipment.code}",
            reason=f"Le cycle actif dure {elapsed:.1f} min, contre un seuil déterministe de {threshold:.1f} min.",
            metric="active_cycle_duration",
            value=round(elapsed, 1),
            threshold=round(threshold, 1),
            unit="min",
            deduplication_key=f"abnormal-cycle:{snapshot.context.site_id}:{cycle.cycle_id}",
            context={"equipmentCode": equipment.code, "baselineMinutes": round(baseline, 1)},
        ))
    return candidates


def detect_predicted_mechanical_failure_risk(
    snapshot: MonitoringSnapshot, settings: Settings
) -> list[MonitoringCandidate]:
    """Alert only when the served Failure-Risk probability meets the artifact threshold."""

    _ = settings
    candidates: list[MonitoringCandidate] = []
    equipment_by_id = {equipment.equipment_id: equipment for equipment in snapshot.equipment}
    for equipment_id, prediction in snapshot.failure_risk.items():
        status = getattr(prediction.status, "value", prediction.status)
        if status != FailureRiskStatus.AVAILABLE.value:
            continue
        probability = prediction.risk_probability
        threshold = prediction.threshold
        if probability is None or threshold is None or probability < threshold:
            continue
        equipment = equipment_by_id.get(equipment_id)
        if equipment is None:
            continue
        horizon = int(prediction.horizon_minutes or 60)
        risk_level = getattr(prediction.risk_level, "value", prediction.risk_level)
        candidates.append(
            MonitoringCandidate(
                detector_id="predicted-mechanical-failure-risk",
                trigger_type=TriggerType.PREDICTED_MECHANICAL_FAILURE_RISK,
                site_id=snapshot.context.site_id,
                shift_id=snapshot.context.shift_id,
                equipment_id=equipment_id,
                detected_at=snapshot.context.sim_now,
                severity=Severity.WARNING,
                title=f"Risque mécanique prédit — {equipment.code}",
                reason=(
                    f"{equipment.code} présente un risque prédit élevé d'entrer en arrêt "
                    f"mécanique dans les {horizon} prochaines minutes."
                ),
                metric="failure_risk_probability",
                value=probability,
                threshold=threshold,
                unit="probability",
                deduplication_key=f"failure-risk:{snapshot.context.site_id}:{equipment_id}",
                alert_source=AlertSource.PREDICTION,
                context={
                    "equipmentCode": equipment.code,
                    "horizonMinutes": horizon,
                    "modelVersion": prediction.model_version,
                    "modelType": prediction.model_type or prediction.served_predictor,
                    "riskLevel": risk_level,
                    "dataClass": prediction.data_class or DATA_CLASS,
                    "topSignals": list(prediction.top_predictive_signals or []),
                    "source": FAILURE_RISK_SOURCE,
                },
            )
        )
    return candidates


DEFAULT_DETECTORS: tuple[Detector, ...] = (
    detect_critical_conditions,
    detect_unexpected_stops,
    detect_prolonged_idle_wait,
    detect_communication_degradation,
    detect_production_deviation,
    detect_abnormal_cycle_duration,
    detect_predicted_mechanical_failure_risk,
)
