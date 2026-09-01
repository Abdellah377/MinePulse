"""Failure-Risk V1 dataset specification.

PROTOTYPE / SYNTHETIC-DATA PROBLEM — not field-validated. This module defines
the prediction problem, leakage-safe windows, temporal split, and readiness
gate. It does not train or score a model.

Horizon choice: measured 5/15/30-minute windows are severely imbalanced;
60 minutes is manageable and every qualifying incident in the current snapshot
has 60 minutes of precursor telemetry. Shorter horizons are not used for V1.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

MODEL_VERSION = "failure_risk_v1"
TRAINING_DATA_TYPE = "synthetic"
DATA_CLASS = "synthetic_prototype"

HORIZON_MINUTES = 60
MIN_LEAD_TIME_MINUTES = 15
STRIDE_MINUTES = 15
HISTORY_LOOKBACK_MINUTES = 60
MIN_HISTORY_MINUTES = 15
INCIDENT_MERGE_GAP = timedelta(minutes=5)

TRAIN_FRACTION = 0.70
VAL_FRACTION = 0.15

MIN_INCIDENTS_NOT_READY = 10
MIN_INCIDENTS_READY = 20
MIN_PRECURSOR_FRAC_NOT_READY = 0.75
MIN_PRECURSOR_FRAC_READY = 0.90
MIN_RATIO_NOT_READY = 0.03
MIN_RATIO_READY = 0.05
MAX_REQUIRED_MISSING_READY = 0.05
MAX_REQUIRED_MISSING_NOT_READY = 0.20

VERDICT_READY = "READY TO BUILD FAILURE-RISK V1"
VERDICT_FIXES = "READY WITH SMALL DATA FIXES"
VERDICT_NOT_READY = "NOT READY — DATA/SIMULATOR CHANGES REQUIRED"

PREDICTION_TARGET = (
    "At prediction time T: will this equipment enter a qualifying "
    "STOPPED_MECHANICAL incident within the next 60 minutes?"
)
POSITIVE_DEFINITION = (
    "A qualifying STOPPED_MECHANICAL incident starts in (T, T + 60 min] "
    "and T is at least 15 minutes before that start."
)
NEGATIVE_DEFINITION = (
    "No qualifying STOPPED_MECHANICAL incident starts in (T, T + 60 min]."
)
HISTORY_WINDOW_STRATEGY = (
    "Use only telemetry, OEM events, state, and maintenance rows with "
    "timestamp <= T; look back 60 minutes for rolling statistics."
)

TELEMETRY_FEATURE_FIELDS: tuple[str, ...] = (
    "engine_temp_c",
    "coolant_temp_c",
    "oil_pressure_kpa",
    "engine_rpm",
    "engine_load_pct",
    "fuel_rate_lph",
    "fuel_level_pct",
    "battery_voltage",
    "speed_kmh",
    "payload_t",
    "communication_quality",
    "engine_hours",
    "odometer_km",
)

DERIVED_FEATURE_GROUPS: tuple[str, ...] = (
    "latest_value",
    "rolling_mean",
    "rolling_min",
    "rolling_max",
    "rolling_std",
    "recent_slope",
    "change_over_interval",
    "deviation_from_equipment_baseline",
)

OPERATIONAL_FEATURE_GROUPS: tuple[str, ...] = (
    "current_equipment_state",
    "recent_workload_if_known_at_T",
)

MAINTENANCE_FEATURE_GROUPS: tuple[str, ...] = (
    "oem_event_count_in_lookback",
    "time_since_last_maintenance_if_populated_before_T",
    "maintenance_count_before_T",
)

UNAVAILABLE_NONBLOCKING_FEATURES: frozenset[str] = frozenset(
    {
        "commission_date",
        "equipment_age",
        "tyre_telemetry",
    }
)

EXCLUDED_FROM_TARGET: frozenset[str] = frozenset(
    {
        "STOPPED_UNDEFINED",
        "NO_DATA",
        "MAINTENANCE",
        "STOPPED_EXTERNAL",
    }
)

FORBIDDEN_FEATURE_NAMES: frozenset[str] = frozenset(
    {
        "scenario_id",
        "scenario_name",
        "hidden_root_cause",
        "run_id",
        "performance_factor",
        "scenario_*_target",
        "progress",
        "stage",
        "profile_id",
        "degradation_progress",
        "internal_failure_countdown",
        "seed",
        "future_telemetry",
        "future_oem_event",
        "downtime_reason_after_failure",
        "future_maintenance",
        "stopped_mechanical_after_start",
    }
)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


@dataclass(frozen=True)
class MechanicalIncident:
    incident_id: str
    equipment_id: int
    start_time: datetime
    end_time: datetime | None


@dataclass(frozen=True)
class FeatureRecord:
    ts: datetime
    name: str
    value: Any


@dataclass(frozen=True)
class LabeledWindow:
    equipment_id: int
    prediction_time: datetime
    label: int | None
    exclude_reason: str | None
    incident_id: str | None
    minutes_to_incident: float | None
    split: str | None = None


@dataclass(frozen=True)
class TemporalSplit:
    train: tuple[LabeledWindow, ...]
    validation: tuple[LabeledWindow, ...]
    test: tuple[LabeledWindow, ...]
    dropped_boundary_windows: int


@dataclass(frozen=True)
class ReadinessEvidence:
    n_incidents: int
    n_open_incidents: int
    n_incidents_with_60min_precursor: int
    n_positive_windows: int
    n_negative_windows: int
    n_excluded_immediate_pre_failure: int
    downtime_events: int
    maintenance_events: int
    required_feature_max_missing_rate: float
    leakage_feature_violations: int
    split_incident_leakage: int
    commission_date_populated: int = 0
    lead_time_applied: bool = True


@dataclass(frozen=True)
class ReadinessResult:
    verdict: str
    do_not_train: bool
    reasons: dict[str, bool]
    notes: tuple[str, ...] = field(default_factory=tuple)


def assert_no_forbidden_features(names: Iterable[str]) -> None:
    blocked = sorted(name for name in names if name in FORBIDDEN_FEATURE_NAMES)
    if blocked:
        raise ValueError(f"Forbidden failure-risk features: {blocked}")


def filter_history_at_or_before(
    records: Sequence[FeatureRecord],
    prediction_time: datetime,
) -> list[FeatureRecord]:
    cutoff = _aware(prediction_time)
    assert cutoff is not None
    return [row for row in records if _aware(row.ts) is not None and _aware(row.ts) <= cutoff]


def positive_negative_ratio(n_positive: int, n_negative: int) -> float | None:
    if n_negative <= 0:
        return None
    return round(n_positive / n_negative, 6)


def imbalance_label(n_positive: int, n_negative: int, n_incidents: int) -> str:
    ratio = positive_negative_ratio(n_positive, n_negative)
    if n_incidents < MIN_INCIDENTS_NOT_READY or ratio is None or n_positive == 0:
        return "unusable"
    if ratio < MIN_RATIO_READY:
        return "severe"
    return "manageable"


def merge_mechanical_incidents(rows: Sequence[dict[str, Any]]) -> list[MechanicalIncident]:
    incidents: list[dict[str, Any]] = []
    for row in rows:
        start = _aware(row["start_time"])
        end = _aware(row.get("end_time"))
        if start is None:
            continue
        if incidents:
            prev = incidents[-1]
            gap_ok = False
            if prev["equipment_id"] == row["equipment_id"] and prev["end_time"] is not None:
                gap_ok = start - prev["end_time"] <= INCIDENT_MERGE_GAP
            if gap_ok:
                prev["end_time"] = end if end is None or prev["end_time"] is None else max(prev["end_time"], end)
                continue
        incidents.append(
            {
                "incident_id": f"{row['equipment_id']}:{start.isoformat()}",
                "equipment_id": int(row["equipment_id"]),
                "start_time": start,
                "end_time": end,
            }
        )
    return [
        MechanicalIncident(
            incident_id=item["incident_id"],
            equipment_id=item["equipment_id"],
            start_time=item["start_time"],
            end_time=item["end_time"],
        )
        for item in incidents
    ]


def _active_incident(
    incidents: Sequence[MechanicalIncident],
    equipment_id: int,
    ts: datetime,
) -> MechanicalIncident | None:
    for item in incidents:
        if item.equipment_id != equipment_id:
            continue
        if ts >= item.start_time and (item.end_time is None or ts < item.end_time):
            return item
    return None


def _next_incident(
    incidents: Sequence[MechanicalIncident],
    equipment_id: int,
    ts: datetime,
) -> MechanicalIncident | None:
    upcoming = [
        item
        for item in incidents
        if item.equipment_id == equipment_id and item.start_time > ts
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda item: item.start_time)


def classify_window(
    *,
    equipment_id: int,
    prediction_time: datetime,
    incidents: Sequence[MechanicalIncident],
    first_telemetry_ts: datetime | None,
    horizon_minutes: int = HORIZON_MINUTES,
    min_lead_time_minutes: int = MIN_LEAD_TIME_MINUTES,
    min_history_minutes: int = MIN_HISTORY_MINUTES,
) -> LabeledWindow:
    t = _aware(prediction_time)
    assert t is not None
    first_ts = _aware(first_telemetry_ts)
    if first_ts is None or t < first_ts or (t - first_ts).total_seconds() / 60.0 < min_history_minutes:
        return LabeledWindow(
            equipment_id=equipment_id,
            prediction_time=t,
            label=None,
            exclude_reason="insufficient_history",
            incident_id=None,
            minutes_to_incident=None,
        )
    active = _active_incident(incidents, equipment_id, t)
    if active is not None:
        return LabeledWindow(
            equipment_id=equipment_id,
            prediction_time=t,
            label=None,
            exclude_reason="active_incident",
            incident_id=active.incident_id,
            minutes_to_incident=0.0,
        )
    nxt = _next_incident(incidents, equipment_id, t)
    if nxt is None:
        return LabeledWindow(
            equipment_id=equipment_id,
            prediction_time=t,
            label=0,
            exclude_reason=None,
            incident_id=None,
            minutes_to_incident=None,
        )
    delta_min = (nxt.start_time - t).total_seconds() / 60.0
    if delta_min > horizon_minutes:
        return LabeledWindow(
            equipment_id=equipment_id,
            prediction_time=t,
            label=0,
            exclude_reason=None,
            incident_id=None,
            minutes_to_incident=None,
        )
    if delta_min < min_lead_time_minutes:
        return LabeledWindow(
            equipment_id=equipment_id,
            prediction_time=t,
            label=None,
            exclude_reason="immediate_pre_failure",
            incident_id=nxt.incident_id,
            minutes_to_incident=round(delta_min, 2),
        )
    return LabeledWindow(
        equipment_id=equipment_id,
        prediction_time=t,
        label=1,
        exclude_reason=None,
        incident_id=nxt.incident_id,
        minutes_to_incident=round(delta_min, 2),
    )


def iter_prediction_times(
    data_start: datetime,
    data_end: datetime,
    *,
    stride_minutes: int = STRIDE_MINUTES,
    horizon_minutes: int = HORIZON_MINUTES,
):
    start = _aware(data_start)
    end = _aware(data_end)
    assert start is not None and end is not None
    last = end - timedelta(minutes=horizon_minutes)
    step = timedelta(minutes=stride_minutes)
    t = start
    while t <= last:
        yield t
        t = t + step


def labeled_windows(
    *,
    equipment_ids: Sequence[int],
    prediction_times: Sequence[datetime],
    incidents: Sequence[MechanicalIncident],
    first_telemetry_ts: dict[int, datetime | None],
    horizon_minutes: int = HORIZON_MINUTES,
    min_lead_time_minutes: int = MIN_LEAD_TIME_MINUTES,
) -> list[LabeledWindow]:
    rows: list[LabeledWindow] = []
    for t in prediction_times:
        for equipment_id in equipment_ids:
            window = classify_window(
                equipment_id=equipment_id,
                prediction_time=t,
                incidents=incidents,
                first_telemetry_ts=first_telemetry_ts.get(equipment_id),
                horizon_minutes=horizon_minutes,
                min_lead_time_minutes=min_lead_time_minutes,
            )
            if window.label is not None:
                rows.append(window)
    return rows


def count_exclusions(
    *,
    equipment_ids: Sequence[int],
    prediction_times: Sequence[datetime],
    incidents: Sequence[MechanicalIncident],
    first_telemetry_ts: dict[int, datetime | None],
    horizon_minutes: int = HORIZON_MINUTES,
    min_lead_time_minutes: int = MIN_LEAD_TIME_MINUTES,
) -> dict[str, int]:
    counts = {
        "insufficient_history": 0,
        "active_incident": 0,
        "immediate_pre_failure": 0,
        "labeled_positive": 0,
        "labeled_negative": 0,
    }
    for t in prediction_times:
        for equipment_id in equipment_ids:
            window = classify_window(
                equipment_id=equipment_id,
                prediction_time=t,
                incidents=incidents,
                first_telemetry_ts=first_telemetry_ts.get(equipment_id),
                horizon_minutes=horizon_minutes,
                min_lead_time_minutes=min_lead_time_minutes,
            )
            if window.exclude_reason:
                counts[window.exclude_reason] = counts.get(window.exclude_reason, 0) + 1
            elif window.label == 1:
                counts["labeled_positive"] += 1
            elif window.label == 0:
                counts["labeled_negative"] += 1
    return counts


def _incident_cutoffs(
    incidents: Sequence[MechanicalIncident],
) -> tuple[dict[str, str], datetime | None, datetime | None]:
    ordered = sorted(incidents, key=lambda item: (item.start_time, item.incident_id))
    n = len(ordered)
    assignment: dict[str, str] = {}
    if n == 0:
        return assignment, None, None
    train_end = int(n * TRAIN_FRACTION)
    val_end = int(n * (TRAIN_FRACTION + VAL_FRACTION))
    if n >= 3:
        train_end = min(max(1, train_end), n - 2)
        val_end = min(max(train_end + 1, val_end), n - 1)
    elif n == 2:
        train_end, val_end = 1, 1
    else:
        train_end, val_end = 1, 1
    for i, item in enumerate(ordered):
        if i < train_end:
            assignment[item.incident_id] = "train"
        elif i < val_end:
            assignment[item.incident_id] = "validation"
        else:
            assignment[item.incident_id] = "test"
    val_items = [item for item in ordered if assignment[item.incident_id] == "validation"]
    test_items = [item for item in ordered if assignment[item.incident_id] == "test"]
    first_val = val_items[0].start_time if val_items else (test_items[0].start_time if test_items else None)
    first_test = test_items[0].start_time if test_items else None
    return assignment, first_val, first_test


def assign_temporal_splits(
    windows: Sequence[LabeledWindow],
    incidents: Sequence[MechanicalIncident],
    *,
    horizon_minutes: int = HORIZON_MINUTES,
) -> TemporalSplit:
    assignment, _first_val_incident, _first_test_incident = _incident_cutoffs(incidents)
    horizon = timedelta(minutes=horizon_minutes)
    train: list[LabeledWindow] = []
    validation: list[LabeledWindow] = []
    test: list[LabeledWindow] = []
    dropped = 0

    assigned_positive_times: dict[str, list[datetime]] = {
        "train": [], "validation": [], "test": [],
    }
    for window in windows:
        if window.incident_id is None or window.label != 1:
            continue
        assigned_positive_times[assignment[window.incident_id]].append(window.prediction_time)
    first_val = min(assigned_positive_times["validation"], default=None)
    first_test = min(assigned_positive_times["test"], default=None)

    def put(window: LabeledWindow, name: str) -> None:
        tagged = replace(window, split=name)
        if name == "train":
            train.append(tagged)
        elif name == "validation":
            validation.append(tagged)
        else:
            test.append(tagged)

    for window in windows:
        if window.label is None:
            continue
        if window.incident_id is not None:
            owner = assignment[window.incident_id]
            t = window.prediction_time
            outside_owner_period = (
                (owner == "train" and first_val is not None and t >= first_val)
                or (owner == "validation" and first_val is not None and t < first_val)
                or (owner == "validation" and first_test is not None and t >= first_test)
                or (owner == "test" and first_test is not None and t < first_test)
            )
            if outside_owner_period:
                dropped += 1
                continue
            put(window, owner)
            continue
        t = window.prediction_time
        horizon_end = t + horizon
        if first_val is not None and t < first_val < horizon_end:
            dropped += 1
            continue
        if first_test is not None and t < first_test < horizon_end:
            dropped += 1
            continue
        if first_val is None or horizon_end <= first_val:
            put(window, "train")
        elif first_test is None or horizon_end <= first_test:
            put(window, "validation")
        else:
            put(window, "test")
    return TemporalSplit(
        train=tuple(train),
        validation=tuple(validation),
        test=tuple(test),
        dropped_boundary_windows=dropped,
    )


def split_has_incident_leakage(split: TemporalSplit) -> bool:
    owners: dict[str, set[str]] = {}
    for name, rows in (
        ("train", split.train),
        ("validation", split.validation),
        ("test", split.test),
    ):
        for window in rows:
            if window.incident_id is None:
                continue
            owners.setdefault(window.incident_id, set()).add(name)
    return any(len(names) > 1 for names in owners.values())


def required_telemetry_missing_rate(rates_pct: Mapping[str, float]) -> float:
    """Return the worst required-sensor missing rate as a 0-1 fraction.

    ``rates_pct`` uses the 0-100 missing percentages from feature builders.
    Optional recency features such as minutes since last maintenance are not
    required sensors and must not block training by themselves.
    """
    selected = [
        float(value) / 100.0
        for name, value in rates_pct.items()
        if any(name == field or name.startswith(f"{field}_") for field in TELEMETRY_FEATURE_FIELDS)
    ]
    return max(selected, default=0.0)


def do_not_train_for(verdict: str) -> bool:
    return verdict != VERDICT_READY


def evaluate_readiness(evidence: ReadinessEvidence) -> ReadinessResult:
    precursor_frac = (
        evidence.n_incidents_with_60min_precursor / evidence.n_incidents
        if evidence.n_incidents
        else 0.0
    )
    ratio = positive_negative_ratio(evidence.n_positive_windows, evidence.n_negative_windows)
    downtime_inconsistent = evidence.n_incidents > 0 and evidence.downtime_events == 0
    lifecycle_mismatch = (
        evidence.n_incidents > 0
        and evidence.downtime_events > 0
        and abs(evidence.downtime_events - evidence.n_incidents) / evidence.n_incidents > 0.25
    )
    too_few = evidence.n_incidents < MIN_INCIDENTS_NOT_READY
    unusable_precursor = evidence.n_incidents > 0 and precursor_frac < MIN_PRECURSOR_FRAC_NOT_READY
    imbalance_unusable = (
        evidence.n_incidents >= MIN_INCIDENTS_NOT_READY
        and (ratio is None or evidence.n_positive_windows == 0 or ratio < MIN_RATIO_NOT_READY)
    )
    missing_critical = evidence.required_feature_max_missing_rate > MAX_REQUIRED_MISSING_NOT_READY
    leakage = (
        evidence.leakage_feature_violations > 0
        or evidence.split_incident_leakage > 0
        or not evidence.lead_time_applied
    )
    not_ready = (
        too_few
        or unusable_precursor
        or imbalance_unusable
        or downtime_inconsistent
        or missing_critical
        or leakage
    )
    small_n = MIN_INCIDENTS_NOT_READY <= evidence.n_incidents < MIN_INCIDENTS_READY
    precursor_soft = (
        evidence.n_incidents >= MIN_INCIDENTS_READY
        and MIN_PRECURSOR_FRAC_NOT_READY <= precursor_frac < MIN_PRECURSOR_FRAC_READY
    )
    imbalance_soft = (
        ratio is not None
        and MIN_RATIO_NOT_READY <= ratio < MIN_RATIO_READY
        and evidence.n_incidents >= MIN_INCIDENTS_READY
    )
    missing_soft = MAX_REQUIRED_MISSING_READY < evidence.required_feature_max_missing_rate <= MAX_REQUIRED_MISSING_NOT_READY
    if not_ready:
        verdict = VERDICT_NOT_READY
    elif small_n or precursor_soft or imbalance_soft or missing_soft or lifecycle_mismatch:
        verdict = VERDICT_FIXES
    else:
        verdict = VERDICT_READY
    reasons = {
        "too_few_independent_incidents": too_few,
        "unusable_precursor_coverage": unusable_precursor,
        "class_imbalance_unusable": imbalance_unusable,
        "downtime_lifecycle_inconsistent": downtime_inconsistent,
        "critical_missing_required_feature": missing_critical,
        "critical_leakage": leakage,
        "lead_time_gap_not_applied": not evidence.lead_time_applied,
        "incident_count_below_ready_bar": small_n,
        "precursor_coverage_partial": precursor_soft,
        "class_imbalance_severe": imbalance_soft,
        "required_feature_partially_missing": missing_soft,
        "lifecycle_count_mismatch": lifecycle_mismatch,
        "commission_date_missing": False,
        "equipment_age_excluded_from_v1": True,
    }
    notes = []
    if evidence.commission_date_populated == 0:
        notes.append("commission_date is unpopulated; equipment age is excluded from V1 and is not a blocker.")
    if evidence.n_excluded_immediate_pre_failure:
        notes.append(
            f"{evidence.n_excluded_immediate_pre_failure} windows dropped for being inside the "
            f"{MIN_LEAD_TIME_MINUTES}-minute immediate-failure gap."
        )
    return ReadinessResult(
        verdict=verdict,
        do_not_train=do_not_train_for(verdict),
        reasons=reasons,
        notes=tuple(notes),
    )


def specification_dict() -> dict[str, Any]:
    return {
        "model_version": MODEL_VERSION,
        "recommended_horizon_min": HORIZON_MINUTES,
        "minimum_lead_time_min": MIN_LEAD_TIME_MINUTES,
        "prediction_target": PREDICTION_TARGET,
        "positive_definition": POSITIVE_DEFINITION,
        "negative_definition": NEGATIVE_DEFINITION,
        "history_window": HISTORY_WINDOW_STRATEGY,
        "sampling_stride_min": STRIDE_MINUTES,
        "history_lookback_min": HISTORY_LOOKBACK_MINUTES,
        "min_history_min": MIN_HISTORY_MINUTES,
        "temporal_split": {
            "strategy": "chronological incident-grouped 70/15/15",
            "train_fraction": TRAIN_FRACTION,
            "validation_fraction": VAL_FRACTION,
            "test_fraction": round(1.0 - TRAIN_FRACTION - VAL_FRACTION, 2),
            "rule": (
                "Split qualifying incidents by start_time. Every window labeled by an "
                "incident stays in that incident's split. Negative windows whose 60-minute "
                "horizon crosses a split boundary are dropped."
            ),
        },
        "allowed_feature_groups": {
            "telemetry_current": list(TELEMETRY_FEATURE_FIELDS),
            "telemetry_derived": list(DERIVED_FEATURE_GROUPS),
            "operational": list(OPERATIONAL_FEATURE_GROUPS),
            "maintenance_oem": list(MAINTENANCE_FEATURE_GROUPS),
        },
        "unavailable_nonblocking_features": sorted(UNAVAILABLE_NONBLOCKING_FEATURES),
        "forbidden_features": sorted(FORBIDDEN_FEATURE_NAMES),
        "excluded_from_mechanical_target": sorted(EXCLUDED_FROM_TARGET),
        "horizon_rationale": (
            "5/15/30-minute horizons are severely imbalanced on the current snapshot. "
            "60 minutes is manageable, has full precursor coverage, and sits inside the "
            "synthetic degradation window without using hidden simulator labels."
        ),
        "lead_time_rationale": (
            "Telemetry cadence is 120 seconds. 72.9% of last samples immediately before "
            "stop already exceed an OEM warn/critical threshold. A 15-minute gap (about "
            "7–8 samples, aligned with the 15-minute stride) forces V1 to predict an "
            "approaching failure rather than the final collapse."
        ),
    }
