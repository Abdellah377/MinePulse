"""Point-in-time Failure-Risk V1 features.

Every value must be knowable at prediction time T. History uses only rows with
timestamp <= T inside the 60-minute lookback.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import sqrt
from typing import Any

from app.ml.failure_risk.dataset import (
    EventSample,
    FailureRiskSnapshot,
    MaintenanceSample,
    StateInterval,
    TelemetrySample,
)
from app.ml.failure_risk.spec import (
    FORBIDDEN_FEATURE_NAMES,
    HISTORY_LOOKBACK_MINUTES,
    TELEMETRY_FEATURE_FIELDS,
    LabeledWindow,
    assert_no_forbidden_features,
    filter_history_at_or_before,
)
from app.oem.thresholds import classify_value
from app.ml.failure_risk.spec import FeatureRecord as SpecFeatureRecord

MISSING_CAT = "__missing__"

CORE_SENSORS = (
    "engine_temp_c",
    "coolant_temp_c",
    "oil_pressure_kpa",
    "battery_voltage",
)
WORKLOAD_SENSORS = (
    "engine_load_pct",
    "engine_rpm",
    "fuel_rate_lph",
)
LATEST_ONLY_SENSORS = (
    "speed_kmh",
    "payload_t",
    "communication_quality",
    "fuel_level_pct",
    "engine_hours",
    "odometer_km",
)

CATEGORICAL_FEATURES = ("current_state",)
NUMERIC_FEATURES: tuple[str, ...] = (
    *(f"{name}_{stat}" for name in CORE_SENSORS for stat in ("latest", "mean", "std", "slope", "change")),
    *(f"{name}_{stat}" for name in WORKLOAD_SENSORS for stat in ("latest", "mean")),
    *(f"{name}_latest" for name in LATEST_ONLY_SENSORS),
    "oem_event_count_lookback",
    "minutes_since_last_oem_event",
    "maintenance_count_before_t",
    "minutes_since_last_completed_maintenance",
)
TEMPORAL_EXTRA_FEATURES: tuple[str, ...] = (
    *(f"{name}_{stat}" for name in CORE_SENSORS for stat in ("min", "max", "mean_15m")),
    "oem_warn_sample_count_lookback",
    "consecutive_abnormal_samples",
)
FEATURE_NAMES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
FEATURE_VERSION = "failure_risk_features_v1"


def _history(
    samples: list[TelemetrySample],
    equipment_id: int,
    prediction_time: datetime,
) -> list[TelemetrySample]:
    lo = prediction_time - timedelta(minutes=HISTORY_LOOKBACK_MINUTES)
    return [
        sample
        for sample in samples
        if sample.equipment_id == equipment_id and lo <= sample.ts <= prediction_time
    ]


def _series(history: list[TelemetrySample], name: str) -> tuple[list[float], list[float]]:
    times: list[float] = []
    values: list[float] = []
    if not history:
        return times, values
    origin = history[0].ts
    for sample in history:
        value = sample.values.get(name)
        if value is None:
            continue
        times.append((sample.ts - origin).total_seconds() / 60.0)
        values.append(float(value))
    return times, values


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    assert mean is not None
    var = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return sqrt(var)


def _slope(times: list[float], values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    x_mean = _mean(times)
    y_mean = _mean(values)
    assert x_mean is not None and y_mean is not None
    denom = sum((x - x_mean) ** 2 for x in times)
    if denom == 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(times, values)) / denom


def _current_state(states: list[StateInterval], equipment_id: int, prediction_time: datetime) -> str:
    overlapping = [
        item
        for item in states
        if item.equipment_id == equipment_id
        and item.start_time <= prediction_time
        and (item.end_time is None or item.end_time > prediction_time)
    ]
    if not overlapping:
        return MISSING_CAT
    current = max(overlapping, key=lambda item: item.start_time)
    return current.state or MISSING_CAT


def _oem_features(
    events: list[EventSample],
    equipment_id: int,
    prediction_time: datetime,
) -> tuple[float, float | None]:
    lo = prediction_time - timedelta(minutes=HISTORY_LOOKBACK_MINUTES)
    prior = [event for event in events if event.equipment_id == equipment_id and event.ts <= prediction_time]
    lookback = [event for event in prior if event.ts >= lo]
    last = max((event.ts for event in prior), default=None)
    minutes = (prediction_time - last).total_seconds() / 60.0 if last is not None else None
    return float(len(lookback)), minutes


def _maintenance_features(
    rows: list[MaintenanceSample],
    equipment_id: int,
    prediction_time: datetime,
) -> tuple[float, float | None]:
    started = [row for row in rows if row.equipment_id == equipment_id and row.start_time < prediction_time]
    completed = [
        row.actual_end_time
        for row in started
        if row.actual_end_time is not None and row.actual_end_time < prediction_time
    ]
    last = max(completed) if completed else None
    minutes = (prediction_time - last).total_seconds() / 60.0 if last is not None else None
    return float(len(started)), minutes


@dataclass(frozen=True)
class FeatureRow:
    equipment_id: int
    prediction_time: datetime
    label: int | None
    incident_id: str | None
    minutes_to_incident: float | None
    split: str | None
    values: dict[str, Any]


def _recent_mean(history: list[TelemetrySample], name: str, prediction_time: datetime, minutes: int) -> float | None:
    lo = prediction_time - timedelta(minutes=minutes)
    values = [
        float(sample.values[name])
        for sample in history
        if sample.ts >= lo and sample.values.get(name) is not None
    ]
    return _mean(values)


def _abnormal_lookback(history: list[TelemetrySample]) -> tuple[float, float]:
    warn_count = 0.0
    consecutive = 0
    longest = 0
    for sample in history:
        abnormal = False
        for name in CORE_SENSORS:
            value = sample.values.get(name)
            if value is None:
                continue
            if classify_value(name, float(value)) in {"warning", "critical"}:
                warn_count += 1.0
                abnormal = True
                break
        consecutive = consecutive + 1 if abnormal else 0
        longest = max(longest, consecutive)
    return warn_count, float(longest)


def _sensor_stats(history: list[TelemetrySample], name: str) -> dict[str, float | None]:
    times, values = _series(history, name)
    latest = values[-1] if values else None
    return {
        "latest": latest,
        "mean": _mean(values),
        "std": _std(values),
        "slope": _slope(times, values),
        "change": (values[-1] - values[0]) if len(values) >= 2 else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def features_for_window(window: LabeledWindow, snapshot: FailureRiskSnapshot) -> FeatureRow:
    records = [
        SpecFeatureRecord(ts=sample.ts, name="telemetry", value=None)
        for sample in snapshot.telemetry
        if sample.equipment_id == window.equipment_id
    ]
    kept = filter_history_at_or_before(records, window.prediction_time)
    assert all(row.ts <= window.prediction_time for row in kept)
    history = _history(snapshot.telemetry, window.equipment_id, window.prediction_time)
    values: dict[str, Any] = {"current_state": _current_state(snapshot.states, window.equipment_id, window.prediction_time)}
    for name in CORE_SENSORS:
        stats = _sensor_stats(history, name)
        for stat, value in stats.items():
            values[f"{name}_{stat}"] = value
    for name in WORKLOAD_SENSORS:
        stats = _sensor_stats(history, name)
        values[f"{name}_latest"] = stats["latest"]
        values[f"{name}_mean"] = stats["mean"]
    for name in LATEST_ONLY_SENSORS:
        stats = _sensor_stats(history, name)
        values[f"{name}_latest"] = stats["latest"]
    oem_count, oem_minutes = _oem_features(snapshot.oem_events, window.equipment_id, window.prediction_time)
    maint_count, maint_minutes = _maintenance_features(
        snapshot.maintenance, window.equipment_id, window.prediction_time
    )
    values["oem_event_count_lookback"] = oem_count
    values["minutes_since_last_oem_event"] = oem_minutes
    values["maintenance_count_before_t"] = maint_count
    values["minutes_since_last_completed_maintenance"] = maint_minutes
    for name in CORE_SENSORS:
        values[f"{name}_mean_15m"] = _recent_mean(history, name, window.prediction_time, 15)
    warn_count, consecutive = _abnormal_lookback(history)
    values["oem_warn_sample_count_lookback"] = warn_count
    values["consecutive_abnormal_samples"] = consecutive
    assert_no_forbidden_features(values)
    return FeatureRow(
        equipment_id=window.equipment_id,
        prediction_time=window.prediction_time,
        label=window.label,
        incident_id=window.incident_id,
        minutes_to_incident=window.minutes_to_incident,
        split=window.split,
        values=values,
    )


def build_feature_rows(
    windows: list[LabeledWindow] | tuple[LabeledWindow, ...],
    snapshot: FailureRiskSnapshot,
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> list[FeatureRow]:
    assert_no_forbidden_features(feature_names)
    if not FORBIDDEN_FEATURE_NAMES.isdisjoint(feature_names):
        raise ValueError("Feature schema contains forbidden names.")
    unused = TELEMETRY_FEATURE_FIELDS  # documented source fields; derived names are the schema
    _ = unused
    rows = [features_for_window(window, snapshot) for window in windows]
    allowed = set(feature_names)
    return [
        FeatureRow(
            equipment_id=row.equipment_id,
            prediction_time=row.prediction_time,
            label=row.label,
            incident_id=row.incident_id,
            minutes_to_incident=row.minutes_to_incident,
            split=row.split,
            values={name: row.values.get(name) for name in feature_names if name in allowed},
        )
        for row in rows
    ]


def missing_rates(rows: list[FeatureRow], *, feature_names: tuple[str, ...] = FEATURE_NAMES) -> dict[str, float]:
    if not rows:
        return {name: 0.0 for name in feature_names}
    rates: dict[str, float] = {}
    n = len(rows)
    for name in feature_names:
        missing = 0
        for row in rows:
            value = row.values.get(name)
            if name in CATEGORICAL_FEATURES:
                if value is None or value == MISSING_CAT:
                    missing += 1
            elif value is None:
                missing += 1
        rates[name] = round(100.0 * missing / n, 1)
    return rates
