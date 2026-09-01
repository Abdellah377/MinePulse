"""Read-only operational snapshot and V1 window construction.

Labels and splits come only from app.ml.failure_risk.spec. This module does not
train a model or import simulator internals.

PROTOTYPE / SYNTHETIC-DATA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.db.models import Equipment, MaintenanceEvent, SystemEvent
from app.db.models.telemetry import EquipmentState as EquipmentStateRow
from app.db.models.telemetry import EquipmentTelemetry
from app.ml.failure_risk.spec import (
    HORIZON_MINUTES,
    STRIDE_MINUTES,
    TELEMETRY_FEATURE_FIELDS,
    MechanicalIncident,
    ReadinessEvidence,
    TemporalSplit,
    assign_temporal_splits,
    count_exclusions,
    iter_prediction_times,
    labeled_windows,
    merge_mechanical_incidents,
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


def readiness_evidence(
    snapshot: FailureRiskSnapshot,
    split: TemporalSplit,
    exclusions: dict[str, int],
    incidents: list[MechanicalIncident],
    *,
    missing_rate_max: float,
    leakage_feature_violations: int,
) -> ReadinessEvidence:
    windows = list(split.train) + list(split.validation) + list(split.test)
    precursor_ids = {
        window.incident_id
        for window in windows
        if window.incident_id
        and window.label == 1
        and window.minutes_to_incident is not None
        and window.minutes_to_incident >= 55
    }
    return ReadinessEvidence(
        n_incidents=len(incidents),
        n_open_incidents=sum(1 for item in incidents if item.end_time is None),
        n_incidents_with_60min_precursor=len(precursor_ids),
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
