"""Read-only operational snapshot and V1 window construction.

Labels and splits come only from app.ml.failure_risk.spec. This module does not
train a model or import simulator internals.

PROTOTYPE / SYNTHETIC-DATA.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.db.models import Equipment, MaintenanceEvent, SystemEvent
from app.db.models.telemetry import EquipmentState as EquipmentStateRow
from app.db.models.telemetry import EquipmentTelemetry
from app.ml.failure_risk.spec import (
    HISTORY_LOOKBACK_MINUTES,
    HORIZON_MINUTES,
    PRECURSOR_COVERAGE_MINUTES,
    STRIDE_MINUTES,
    TELEMETRY_FEATURE_FIELDS,
    LabeledWindow,
    MechanicalIncident,
    ReadinessEvidence,
    TemporalSplit,
    assign_temporal_splits,
    classify_window,
    count_exclusions,
    iter_prediction_times,
    labeled_windows,
    long_horizon_grid_hit,
    merge_mechanical_incidents,
    positive_negative_ratio,
    split_has_incident_leakage,
)
from app.oem.catalog import EVENT_TYPE_TO_CODE


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


@dataclass(frozen=True)
class EquipmentInfo:
    equipment_id: int
    code: str


@dataclass(frozen=True)
class TelemetrySample:
    equipment_id: int
    ts: datetime
    values: dict[str, float | None]


@dataclass(frozen=True)
class StateInterval:
    equipment_id: int
    state: str
    start_time: datetime
    end_time: datetime | None


@dataclass(frozen=True)
class EventSample:
    equipment_id: int
    ts: datetime
    event_type: str


@dataclass(frozen=True)
class MaintenanceSample:
    equipment_id: int
    start_time: datetime
    actual_end_time: datetime | None


@dataclass
class FailureRiskSnapshot:
    equipment: dict[int, EquipmentInfo]
    telemetry: list[TelemetrySample]
    states: list[StateInterval]
    oem_events: list[EventSample]
    maintenance: list[MaintenanceSample]


def load_snapshot(session: Session, *, site_id: int | None = None) -> FailureRiskSnapshot:
    equipment_query = select(Equipment)
    if site_id is not None:
        equipment_query = equipment_query.where(Equipment.site_id == site_id)
    equipment = {
        int(row.equipment_id): EquipmentInfo(equipment_id=int(row.equipment_id), code=str(row.code))
        for row in session.scalars(equipment_query).all()
    }
    telemetry_query = select(EquipmentTelemetry).order_by(EquipmentTelemetry.ts)
    state_query = select(EquipmentStateRow).order_by(EquipmentStateRow.start_time)
    event_query = select(SystemEvent).order_by(SystemEvent.ts)
    maintenance_query = select(MaintenanceEvent).order_by(MaintenanceEvent.start_time)
    if site_id is not None:
        telemetry_query = telemetry_query.join(
            Equipment, EquipmentTelemetry.equipment_id == Equipment.equipment_id
        ).where(Equipment.site_id == site_id)
        state_query = state_query.join(
            Equipment, EquipmentStateRow.equipment_id == Equipment.equipment_id
        ).where(Equipment.site_id == site_id)
        event_query = event_query.join(
            Equipment, SystemEvent.equipment_id == Equipment.equipment_id
        ).where(Equipment.site_id == site_id)
        maintenance_query = maintenance_query.join(
            Equipment, MaintenanceEvent.equipment_id == Equipment.equipment_id
        ).where(Equipment.site_id == site_id)
    telemetry: list[TelemetrySample] = []
    for row in session.scalars(telemetry_query).all():
        ts = _aware(row.ts)
        if ts is None:
            continue
        values = {name: _float(getattr(row, name, None)) for name in TELEMETRY_FEATURE_FIELDS}
        telemetry.append(TelemetrySample(equipment_id=int(row.equipment_id), ts=ts, values=values))
    states: list[StateInterval] = []
    for row in session.scalars(state_query).all():
        start = _aware(row.start_time)
        if start is None:
            continue
        state = row.state.value if hasattr(row.state, "value") else str(row.state)
        states.append(
            StateInterval(
                equipment_id=int(row.equipment_id),
                state=state,
                start_time=start,
                end_time=_aware(row.end_time),
            )
        )
    oem_types = set(EVENT_TYPE_TO_CODE)
    oem_events: list[EventSample] = []
    for row in session.scalars(event_query).all():
        if row.equipment_id is None or row.event_type not in oem_types:
            continue
        ts = _aware(row.ts)
        if ts is None:
            continue
        oem_events.append(EventSample(equipment_id=int(row.equipment_id), ts=ts, event_type=str(row.event_type)))
    maintenance: list[MaintenanceSample] = []
    for row in session.scalars(maintenance_query).all():
        start = _aware(row.start_time)
        if start is None:
            continue
        maintenance.append(
            MaintenanceSample(
                equipment_id=int(row.equipment_id),
                start_time=start,
                actual_end_time=_aware(row.actual_end_time),
            )
        )
    return FailureRiskSnapshot(
        equipment=equipment,
        telemetry=telemetry,
        states=states,
        oem_events=oem_events,
        maintenance=maintenance,
    )


def mechanical_incidents(snapshot: FailureRiskSnapshot) -> list[MechanicalIncident]:
    rows = [
        {
            "equipment_id": item.equipment_id,
            "start_time": item.start_time,
            "end_time": item.end_time,
        }
        for item in snapshot.states
        if item.state == EquipmentState.STOPPED_MECHANICAL.value or item.state == "STOPPED_MECHANICAL"
    ]
    rows.sort(key=lambda item: (item["equipment_id"], item["start_time"]))
    return merge_mechanical_incidents(rows)


def telemetry_span(snapshot: FailureRiskSnapshot) -> tuple[datetime | None, datetime | None, dict[int, datetime]]:
    first_ts: dict[int, datetime] = {}
    last_ts: dict[int, datetime] = {}
    for sample in snapshot.telemetry:
        first_ts[sample.equipment_id] = min(first_ts.get(sample.equipment_id, sample.ts), sample.ts)
        last_ts[sample.equipment_id] = max(last_ts.get(sample.equipment_id, sample.ts), sample.ts)
    if not first_ts:
        return None, None, {}
    return min(first_ts.values()), max(last_ts.values()), first_ts


def build_window_split(snapshot: FailureRiskSnapshot) -> tuple[TemporalSplit, dict[str, int], list[MechanicalIncident]]:
    incidents = mechanical_incidents(snapshot)
    data_start, data_end, first_ts = telemetry_span(snapshot)
    empty = TemporalSplit(train=(), validation=(), test=(), dropped_boundary_windows=0)
    if data_start is None or data_end is None:
        return empty, {"insufficient_history": 0, "active_incident": 0, "immediate_pre_failure": 0, "labeled_positive": 0, "labeled_negative": 0}, incidents
    equipment_ids = sorted({sample.equipment_id for sample in snapshot.telemetry})
    times = list(iter_prediction_times(data_start, data_end, stride_minutes=STRIDE_MINUTES, horizon_minutes=HORIZON_MINUTES))
    first_map: dict[int, datetime | None] = {eid: first_ts.get(eid) for eid in equipment_ids}
    exclusions = count_exclusions(
        equipment_ids=equipment_ids,
        prediction_times=times,
        incidents=incidents,
        first_telemetry_ts=first_map,
    )
    labeled = labeled_windows(
        equipment_ids=equipment_ids,
        prediction_times=times,
        incidents=incidents,
        first_telemetry_ts=first_map,
    )
    split = assign_temporal_splits(labeled, incidents)
    return split, exclusions, incidents


def _state_name(state: Any) -> str:
    return str(getattr(state, "value", state))


def downtime_event_count(snapshot: FailureRiskSnapshot) -> int:
    return sum(1 for item in snapshot.states if _state_name(item.state) == "STOPPED_MECHANICAL")


def observable_precursor_minutes(
    snapshot: FailureRiskSnapshot,
    incident: MechanicalIncident,
    *,
    lookback_minutes: int = HISTORY_LOOKBACK_MINUTES,
) -> float | None:
    """Minutes from the earliest lookback telemetry sample to the stop.

    Returns None when the lookback contains no samples before ``start_time``.
    """
    start = incident.start_time
    earliest = start - timedelta(minutes=lookback_minutes)
    samples = [
        sample.ts
        for sample in snapshot.telemetry
        if sample.equipment_id == incident.equipment_id and earliest <= sample.ts < start
    ]
    if not samples:
        return None
    return round((start - min(samples)).total_seconds() / 60.0, 2)


def _classified_windows(
    snapshot: FailureRiskSnapshot,
    incidents: Sequence[MechanicalIncident],
    *,
    stride_minutes: int,
) -> tuple[list[LabeledWindow], list[datetime], dict[int, datetime]]:
    data_start, data_end, first_ts = telemetry_span(snapshot)
    if data_start is None or data_end is None:
        return [], [], first_ts
    equipment_ids = sorted({sample.equipment_id for sample in snapshot.telemetry})
    times = list(
        iter_prediction_times(
            data_start,
            data_end,
            stride_minutes=stride_minutes,
            horizon_minutes=HORIZON_MINUTES,
        )
    )
    first_map = {eid: first_ts.get(eid) for eid in equipment_ids}
    classified = [
        classify_window(
            equipment_id=equipment_id,
            prediction_time=prediction_time,
            incidents=incidents,
            first_telemetry_ts=first_map.get(equipment_id),
        )
        for prediction_time in times
        for equipment_id in equipment_ids
    ]
    return classified, times, first_ts


def _stride_comparison_stats(
    snapshot: FailureRiskSnapshot,
    incidents: Sequence[MechanicalIncident],
    *,
    strides: tuple[int, ...] = (15, 10, 5),
    baseline_stride: int = STRIDE_MINUTES,
) -> dict[str, Any]:
    data_start, data_end, first_ts = telemetry_span(snapshot)
    if data_start is None or data_end is None:
        return {}
    equipment_ids = sorted({sample.equipment_id for sample in snapshot.telemetry})
    first_map = {eid: first_ts.get(eid) for eid in equipment_ids}
    baseline_times = 0
    report: dict[str, Any] = {}
    for stride in strides:
        times = list(
            iter_prediction_times(
                data_start,
                data_end,
                stride_minutes=stride,
                horizon_minutes=HORIZON_MINUTES,
            )
        )
        if stride == baseline_stride:
            baseline_times = len(times)
        labeled = labeled_windows(
            equipment_ids=equipment_ids,
            prediction_times=times,
            incidents=incidents,
            first_telemetry_ts=first_map,
        )
        positives = [row for row in labeled if row.label == 1]
        labeled_ge55 = {
            row.incident_id
            for row in positives
            if row.incident_id
            and row.minutes_to_incident is not None
            and row.minutes_to_incident >= PRECURSOR_COVERAGE_MINUTES
        }
        grid_hits = sum(1 for item in incidents if long_horizon_grid_hit(item.start_time, times))
        n_pos = len(positives)
        n_neg = sum(1 for row in labeled if row.label == 0)
        report[str(stride)] = {
            "stride_minutes": stride,
            "prediction_times": len(times),
            "labeled_windows": len(labeled),
            "positive_windows": n_pos,
            "negative_windows": n_neg,
            "class_ratio": positive_negative_ratio(n_pos, n_neg),
            "incidents_with_labeled_ge_55": len(labeled_ge55),
            "incidents_with_grid_in_55_to_60": grid_hits,
            "size_multiplier_vs_v1": (
                round(len(times) / baseline_times, 3) if baseline_times else None
            ),
        }
    if baseline_times:
        for stats in report.values():
            stats["size_multiplier_vs_v1"] = round(stats["prediction_times"] / baseline_times, 3)
    return report


def account_precursor_coverage(
    snapshot: FailureRiskSnapshot,
    incidents: Sequence[MechanicalIncident],
    split: TemporalSplit,
    *,
    stride_comparison: bool = True,
) -> dict[str, Any]:
    """Explain why each mechanical incident does or does not contribute coverage.

    Distinguishes simulator history (observable telemetry before stop) from
    dataset discards (lead-time, stride phase, split-boundary purge).
    """
    data_start, _data_end, first_ts = telemetry_span(snapshot)
    classified, times, _ = _classified_windows(snapshot, incidents, stride_minutes=STRIDE_MINUTES)
    surviving = list(split.train) + list(split.validation) + list(split.test)
    surviving_by_incident: dict[str, list[LabeledWindow]] = {}
    for window in surviving:
        if window.incident_id and window.label == 1:
            surviving_by_incident.setdefault(window.incident_id, []).append(window)

    def _related(incident: MechanicalIncident) -> list[LabeledWindow]:
        related: list[LabeledWindow] = []
        for window in classified:
            if window.equipment_id != incident.equipment_id:
                continue
            if window.incident_id == incident.incident_id:
                related.append(window)
                continue
            delta = (incident.start_time - window.prediction_time).total_seconds() / 60.0
            if window.incident_id is None and 0 < delta <= HORIZON_MINUTES:
                related.append(window)
            elif (
                window.exclude_reason == "active_incident"
                and 0 < delta <= HORIZON_MINUTES
            ):
                related.append(window)
        return related

    rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    loss_counts: Counter[str] = Counter()
    informational = frozenset(
        {"HAS_LEAD_TIME_EXCLUSIONS", "NONE", "STRIDE_MISSES_55_TO_60_MIN_WINDOW"}
    )
    n_observable = 0
    n_raw_positive = 0
    n_raw_ge55 = 0
    n_surviving_positive = 0
    n_surviving_ge55 = 0
    n_usable = 0
    for incident in incidents:
        observable = observable_precursor_minutes(snapshot, incident)
        before_stop = [
            sample.ts
            for sample in snapshot.telemetry
            if sample.equipment_id == incident.equipment_id and sample.ts < incident.start_time
        ]
        minutes_from_sim_start = (
            round((incident.start_time - data_start).total_seconds() / 60.0, 2)
            if data_start is not None
            else None
        )
        first_equipment_ts = first_ts.get(incident.equipment_id)
        minutes_from_first_telemetry = (
            round((incident.start_time - first_equipment_ts).total_seconds() / 60.0, 2)
            if first_equipment_ts is not None
            else None
        )
        classified_rows = _related(incident)
        raw_pos = [row for row in classified_rows if row.label == 1]
        raw_ge55 = [
            row
            for row in raw_pos
            if row.minutes_to_incident is not None
            and row.minutes_to_incident >= PRECURSOR_COVERAGE_MINUTES
        ]
        surviving_pos = surviving_by_incident.get(incident.incident_id, [])
        surviving_ge55 = [
            row
            for row in surviving_pos
            if row.minutes_to_incident is not None
            and row.minutes_to_incident >= PRECURSOR_COVERAGE_MINUTES
        ]
        raw_max = max((row.minutes_to_incident or 0.0 for row in raw_pos), default=None)
        surviving_max = max((row.minutes_to_incident or 0.0 for row in surviving_pos), default=None)
        reasons: list[str] = []
        if not before_stop:
            reasons.append("NO_TELEMETRY_BEFORE_STOP")
        if observable is None:
            reasons.append("NO_TELEMETRY_IN_LOOKBACK")
        elif observable < PRECURSOR_COVERAGE_MINUTES:
            reasons.append("INSUFFICIENT_OBSERVABLE_HISTORY")
        if minutes_from_sim_start is not None and minutes_from_sim_start < PRECURSOR_COVERAGE_MINUTES:
            reasons.append("FAILURE_TOO_EARLY_AFTER_SIM_START")
        if any(row.exclude_reason == "insufficient_history" for row in classified_rows) and not raw_pos:
            reasons.append("INSUFFICIENT_HISTORY")
        if any(row.exclude_reason == "active_incident" for row in classified_rows) and not raw_pos:
            reasons.append("ACTIVE_INCIDENT_CONFLICT")
        if any(row.exclude_reason == "immediate_pre_failure" for row in classified_rows):
            reasons.append("HAS_LEAD_TIME_EXCLUSIONS")
        if not raw_pos:
            reasons.append("NO_LABELED_POSITIVE")
        elif not raw_ge55:
            reasons.append("STRIDE_MISSES_55_TO_60_MIN_WINDOW")
        if raw_ge55 and not surviving_ge55:
            reasons.append("WINDOW_REMOVED_BY_SPLIT_BOUNDARY")
        if raw_pos and not surviving_pos:
            reasons.append("ALL_POSITIVES_REMOVED_BY_SPLIT_BOUNDARY")
        if not reasons:
            reasons.append("NONE")

        usable = (
            observable is not None
            and observable >= PRECURSOR_COVERAGE_MINUTES
            and bool(surviving_pos)
        )
        if observable is not None and observable >= PRECURSOR_COVERAGE_MINUTES:
            n_observable += 1
        if raw_pos:
            n_raw_positive += 1
        if raw_ge55:
            n_raw_ge55 += 1
        if surviving_pos:
            n_surviving_positive += 1
        if surviving_ge55:
            n_surviving_ge55 += 1
        if usable:
            n_usable += 1
        for reason in reasons:
            reason_counts[reason] += 1
            if not usable and reason not in informational:
                loss_counts[reason] += 1
        rows.append(
            {
                "incident_id": incident.incident_id,
                "equipment_id": incident.equipment_id,
                "observable_minutes": observable,
                "minutes_from_sim_start": minutes_from_sim_start,
                "minutes_from_first_telemetry": minutes_from_first_telemetry,
                "raw_positive_windows": len(raw_pos),
                "raw_max_minutes_to_incident": raw_max,
                "raw_labeled_ge_55": bool(raw_ge55),
                "surviving_positive_windows": len(surviving_pos),
                "surviving_max_minutes_to_incident": surviving_max,
                "surviving_labeled_ge_55": bool(surviving_ge55),
                "usable_precursor": usable,
                "reasons": reasons,
            }
        )

    return {
        "definition": (
            "A usable precursor incident has >=55 minutes of operational telemetry "
            "in the 60-minute lookback before STOPPED_MECHANICAL and at least one "
            "surviving labeled positive window after lead-time and leakage-safe splits. "
            "Labeled minutes_to_incident>=55 on the 15-minute grid is reported as "
            "legacy_labeled_ge_55 and is not the readiness numerator."
        ),
        "precursor_coverage_minutes": PRECURSOR_COVERAGE_MINUTES,
        "horizon_minutes": HORIZON_MINUTES,
        "stride_minutes": STRIDE_MINUTES,
        "counts": {
            "total_incidents": len(incidents),
            "observable_ge_55": n_observable,
            "raw_labeled_positive": n_raw_positive,
            "raw_labeled_ge_55": n_raw_ge55,
            "surviving_lead_time_positive": n_raw_positive,
            "surviving_temporal_split": n_surviving_positive,
            "legacy_surviving_labeled_ge_55": n_surviving_ge55,
            "usable_precursor_incidents": n_usable,
        },
        "loss_by_reason": dict(sorted(loss_counts.items())),
        "flags_by_reason": dict(sorted(reason_counts.items())),
        "grid_in_55_to_60": sum(1 for item in incidents if long_horizon_grid_hit(item.start_time, times)),
        "stride_analysis": _stride_comparison_stats(snapshot, incidents) if stride_comparison else {},
        "incidents": rows,
    }


def readiness_evidence(
    snapshot: FailureRiskSnapshot,
    split: TemporalSplit,
    exclusions: dict[str, int],
    incidents: list[MechanicalIncident],
    *,
    missing_rate_max: float,
    leakage_feature_violations: int,
) -> ReadinessEvidence:
    coverage = account_precursor_coverage(
        snapshot, incidents, split, stride_comparison=False
    )
    return ReadinessEvidence(
        n_incidents=len(incidents),
        n_open_incidents=sum(1 for item in incidents if item.end_time is None),
        n_incidents_with_60min_precursor=int(coverage["counts"]["usable_precursor_incidents"]),
        n_positive_windows=int(exclusions.get("labeled_positive", 0)),
        n_negative_windows=int(exclusions.get("labeled_negative", 0)),
        n_excluded_immediate_pre_failure=int(exclusions.get("immediate_pre_failure", 0)),
        downtime_events=downtime_event_count(snapshot),
        maintenance_events=len(snapshot.maintenance),
        required_feature_max_missing_rate=missing_rate_max,
        leakage_feature_violations=leakage_feature_violations,
        split_incident_leakage=int(split_has_incident_leakage(split)),
        lead_time_applied=True,
    )


def snapshot_summary(snapshot: FailureRiskSnapshot, split: TemporalSplit, exclusions: dict[str, int]) -> dict[str, Any]:
    train_pos = sum(1 for row in split.train if row.label == 1)
    val_pos = sum(1 for row in split.validation if row.label == 1)
    test_pos = sum(1 for row in split.test if row.label == 1)
    return {
        "equipment": len(snapshot.equipment),
        "telemetry_rows": len(snapshot.telemetry),
        "oem_events": len(snapshot.oem_events),
        "maintenance_rows": len(snapshot.maintenance),
        "excluded": exclusions,
        "dropped_boundary_windows": split.dropped_boundary_windows,
        "split_counts": {
            "train": len(split.train),
            "validation": len(split.validation),
            "test": len(split.test),
            "train_positive": train_pos,
            "validation_positive": val_pos,
            "test_positive": test_pos,
        },
    }
