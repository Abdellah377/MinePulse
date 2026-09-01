"""Temporal partitions must be strictly ordered, not merely row-disjoint."""

from datetime import datetime, timedelta, timezone

from app.ml.cycle_time.features import FeatureRow as CycleFeatureRow
from app.ml.cycle_time.train import temporal_split as cycle_temporal_split
from app.ml.failure_risk.spec import (
    LabeledWindow,
    MechanicalIncident,
    assign_temporal_splits,
    split_has_incident_leakage,
)


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def _failure_window(t: int, *, incident: str | None, label: int) -> LabeledWindow:
    return LabeledWindow(
        equipment_id=1,
        prediction_time=_at(t),
        label=label,
        exclude_reason=None,
        incident_id=incident,
        minutes_to_incident=30.0 if incident else None,
    )


def test_failure_partitions_are_strictly_ordered_and_boundary_horizons_are_purged():
    incidents = (
        MechanicalIncident("train-incident", 1, _at(180), _at(210)),
        MechanicalIncident("validation-incident", 1, _at(200), _at(230)),
        MechanicalIncident("test-incident", 1, _at(400), _at(430)),
    )
    windows = (
        _failure_window(120, incident="train-incident", label=1),
        _failure_window(170, incident="train-incident", label=1),
        _failure_window(145, incident="validation-incident", label=1),
        _failure_window(185, incident="validation-incident", label=1),
        _failure_window(350, incident="test-incident", label=1),
        _failure_window(100, incident=None, label=0),
    )

    split = assign_temporal_splits(windows, incidents)

    assert split.train and split.validation and split.test
    assert max(row.prediction_time for row in split.train) < min(
        row.prediction_time for row in split.validation
    )
    assert max(row.prediction_time for row in split.validation) < min(
        row.prediction_time for row in split.test
    )
    assert split.dropped_boundary_windows == 2
    assert not split_has_incident_leakage(split)


def test_cycle_partition_never_splits_equal_prediction_timestamps():
    times = [0, 10, 20, 30, 40, 50, 100, 100, 100, 100]
    rows = [
        CycleFeatureRow(i + 1, i + 1, _at(minutes), 10.0, {})
        for i, minutes in enumerate(times)
    ]

    train, validation, test = cycle_temporal_split(rows)

    timestamp_sets = [
        {row.started_at for row in partition}
        for partition in (train, validation, test)
    ]
    assert timestamp_sets[0].isdisjoint(timestamp_sets[1])
    assert timestamp_sets[0].isdisjoint(timestamp_sets[2])
    assert timestamp_sets[1].isdisjoint(timestamp_sets[2])
