"""Precursor coverage: observable history versus stride-aligned labeled slots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ml.failure_risk.dataset import (
    EquipmentInfo,
    FailureRiskSnapshot,
    StateInterval,
    TelemetrySample,
    account_precursor_coverage,
    build_window_split,
    readiness_evidence,
)
from app.ml.failure_risk.spec import (
    FORBIDDEN_FEATURE_NAMES,
    HORIZON_MINUTES,
    MIN_LEAD_TIME_MINUTES,
    PRECURSOR_COVERAGE_MINUTES,
    STRIDE_MINUTES,
    TELEMETRY_FEATURE_FIELDS,
    iter_prediction_times,
    long_horizon_grid_hit,
    split_has_incident_leakage,
)
from simulator.failure_population import FailurePopulationConfig

T0 = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)


def _at(minutes: int | float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _tel(equipment_id: int, minutes: int, **overrides) -> TelemetrySample:
    values = {name: 0.0 for name in TELEMETRY_FEATURE_FIELDS}
    values.update(
        {
            "engine_temp_c": 90.0,
            "coolant_temp_c": 80.0,
            "oil_pressure_kpa": 280.0,
            "battery_voltage": 26.0,
            "engine_rpm": 1400.0,
            "engine_load_pct": 40.0,
            "fuel_rate_lph": 20.0,
            "fuel_level_pct": 70.0,
            "speed_kmh": 25.0,
            "payload_t": 180.0,
            "communication_quality": 90.0,
            "engine_hours": 1000.0,
            "odometer_km": 5000.0,
        }
    )
    values.update(overrides)
    return TelemetrySample(equipment_id=equipment_id, ts=_at(minutes), values=values)


def _snapshot(
    *,
    end_min: int = 400,
    incidents: list[tuple[int, int]] | None = None,
    telemetry_end: int | None = None,
    start_min: int = 0,
) -> FailureRiskSnapshot:
    last = telemetry_end if telemetry_end is not None else end_min
    telemetry = [_tel(1, minute) for minute in range(start_min, last + 1, 2)]
    state_rows = [StateInterval(1, "MOVING_LOADED", _at(start_min), None)]
    if incidents:
        for start, end in incidents:
            state_rows.append(StateInterval(1, "STOPPED_MECHANICAL", _at(start), _at(end)))
    return FailureRiskSnapshot(
        equipment={1: EquipmentInfo(1, "TRK-001")},
        telemetry=telemetry,
        states=state_rows,
        oem_events=[],
        maintenance=[],
    )


def test_fifty_five_minute_floor_is_horizon_with_cadence_slack_not_a_shorter_target():
    assert HORIZON_MINUTES == 60
    assert PRECURSOR_COVERAGE_MINUTES == 55
    assert STRIDE_MINUTES == 15
    assert HORIZON_MINUTES - PRECURSOR_COVERAGE_MINUTES == 5


def test_fifteen_minute_stride_hits_the_55_to_60_slot_for_only_one_third_of_offsets():
    hits = 0
    for offset in range(STRIDE_MINUTES):
        incident_min = 180 + offset
        times = list(iter_prediction_times(_at(0), _at(incident_min + HORIZON_MINUTES)))
        if long_horizon_grid_hit(_at(incident_min), times):
            hits += 1
    assert hits == 6
    assert hits / STRIDE_MINUTES <= 0.4


def test_five_minute_stride_always_hits_the_55_to_60_slot_and_inflates_window_count():
    ten_hits = 0
    five_hits = 0
    v1_times = list(iter_prediction_times(_at(0), _at(240), stride_minutes=15))
    ten_times = list(iter_prediction_times(_at(0), _at(240), stride_minutes=10))
    five_times = list(iter_prediction_times(_at(0), _at(240), stride_minutes=5))
    for offset in range(15):
        incident = _at(180 + offset)
        if long_horizon_grid_hit(incident, ten_times):
            ten_hits += 1
        if long_horizon_grid_hit(incident, five_times):
            five_hits += 1
    assert five_hits == 15
    assert ten_hits < 15
    assert len(five_times) / len(v1_times) == pytest.approx(3.0, rel=0.15)
    assert len(ten_times) / len(v1_times) == pytest.approx(1.5, rel=0.15)


def test_incident_with_60_min_history_produces_a_positive_window_for_every_stride_offset():
    for offset in range(STRIDE_MINUTES):
        start = 180 + offset
        snapshot = _snapshot(end_min=start + 80, incidents=[(start, start + 30)])
        split, exclusions, incidents = build_window_split(snapshot)
        windows = list(split.train) + list(split.validation) + list(split.test)
        positives = [row for row in windows if row.label == 1]
        assert incidents
        assert positives
        assert all(
            row.minutes_to_incident is not None
            and MIN_LEAD_TIME_MINUTES <= row.minutes_to_incident <= HORIZON_MINUTES
            for row in positives
        )
        assert exclusions["labeled_positive"] >= 1


def test_readiness_counts_observable_history_not_stride_aligned_55_minute_labels():
    snapshot = _snapshot(end_min=300, incidents=[(188, 220)])
    split, exclusions, incidents = build_window_split(snapshot)
    windows = list(split.train) + list(split.validation) + list(split.test)
    positives = [row for row in windows if row.label == 1]
    assert positives
    assert max(row.minutes_to_incident or 0.0 for row in positives) < PRECURSOR_COVERAGE_MINUTES
    evidence = readiness_evidence(
        snapshot,
        split,
        exclusions,
        incidents,
        missing_rate_max=0.0,
        leakage_feature_violations=0,
    )
    coverage = account_precursor_coverage(snapshot, incidents, split, stride_comparison=False)
    assert evidence.n_incidents == 1
    assert evidence.n_incidents_with_60min_precursor == 1
    assert coverage["counts"]["legacy_surviving_labeled_ge_55"] == 0
    assert coverage["counts"]["observable_ge_55"] == 1
    assert coverage["counts"]["usable_precursor_incidents"] == 1
    assert coverage["incidents"][0]["reasons"] == ["STRIDE_MISSES_55_TO_60_MIN_WINDOW"] or (
        "STRIDE_MISSES_55_TO_60_MIN_WINDOW" in coverage["incidents"][0]["reasons"]
    )


def test_early_incident_remains_counted_but_does_not_satisfy_precursor_coverage():
    snapshot = _snapshot(end_min=120, incidents=[(40, 70)])
    split, exclusions, incidents = build_window_split(snapshot)
    evidence = readiness_evidence(
        snapshot,
        split,
        exclusions,
        incidents,
        missing_rate_max=0.0,
        leakage_feature_violations=0,
    )
    coverage = account_precursor_coverage(snapshot, incidents, split, stride_comparison=False)
    assert evidence.n_incidents == 1
    assert evidence.n_incidents_with_60min_precursor == 0
    reasons = coverage["incidents"][0]["reasons"]
    assert "FAILURE_TOO_EARLY_AFTER_SIM_START" in reasons
    assert "INSUFFICIENT_OBSERVABLE_HISTORY" in reasons
    assert coverage["loss_by_reason"]["FAILURE_TOO_EARLY_AFTER_SIM_START"] == 1


def test_accounting_separates_missing_history_from_stride_phase():
    missing_history = _snapshot(end_min=120, incidents=[(40, 70)])
    stride_miss = _snapshot(end_min=300, incidents=[(188, 220)])
    split_a, _, incidents_a = build_window_split(missing_history)
    split_b, _, incidents_b = build_window_split(stride_miss)
    lost = account_precursor_coverage(missing_history, incidents_a, split_a, stride_comparison=False)
    sampled = account_precursor_coverage(stride_miss, incidents_b, split_b, stride_comparison=False)
    assert lost["counts"]["observable_ge_55"] == 0
    assert sampled["counts"]["observable_ge_55"] == 1
    assert sampled["counts"]["legacy_surviving_labeled_ge_55"] == 0
    assert "STRIDE_MISSES_55_TO_60_MIN_WINDOW" in sampled["flags_by_reason"]
    assert "STRIDE_MISSES_55_TO_60_MIN_WINDOW" not in sampled["loss_by_reason"]


def test_train_validation_test_remain_leakage_safe_and_incident_owned():
    snapshot = _snapshot(
        end_min=1500,
        incidents=[(180 + i * 240, 210 + i * 240) for i in range(6)],
    )
    split, _exclusions, incidents = build_window_split(snapshot)
    assert not split_has_incident_leakage(split)
    owners: dict[str, set[str]] = {}
    for name, rows in (
        ("train", split.train),
        ("validation", split.validation),
        ("test", split.test),
    ):
        for row in rows:
            if row.incident_id:
                owners.setdefault(row.incident_id, set()).add(name)
    assert owners
    assert all(len(names) == 1 for names in owners.values())
    assert max(row.prediction_time for row in split.train) < min(
        row.prediction_time for row in split.validation
    )
    assert max(row.prediction_time for row in split.validation) < min(
        row.prediction_time for row in split.test
    )
    horizon = timedelta(minutes=HORIZON_MINUTES)
    first_val = min(row.prediction_time for row in split.validation)
    first_test = min(row.prediction_time for row in split.test)
    for row in split.train:
        if row.label == 0:
            assert row.prediction_time + horizon <= first_val
    for row in split.validation:
        if row.label == 0:
            assert row.prediction_time + horizon <= first_test
    coverage = account_precursor_coverage(snapshot, incidents, split, stride_comparison=False)
    assert coverage["counts"]["usable_precursor_incidents"] == coverage["counts"]["surviving_temporal_split"]
    assert coverage["counts"]["usable_precursor_incidents"] == len(incidents)


def test_failure_population_keeps_gradual_degradation_and_warmup_policy():
    config = FailurePopulationConfig(enabled=True)
    assert config.warmup_min == 20.0
    assert config.degradation_min >= 70.0
    assert config.degradation_max >= config.degradation_min
    assert config.warmup_min + config.degradation_min >= 90.0


def test_precursor_accounting_is_deterministic_and_hides_simulator_truth():
    snapshot = _snapshot(end_min=300, incidents=[(180, 210), (188, 220)])
    split, _exclusions, incidents = build_window_split(snapshot)
    first = account_precursor_coverage(snapshot, incidents, split)
    second = account_precursor_coverage(snapshot, incidents, split)
    assert first == second
    blob = str(first)
    for token in FORBIDDEN_FEATURE_NAMES:
        assert token not in blob
    for token in ("scenario_id", "hidden_root_cause", "profile_id", "progress"):
        assert token not in blob
    assert STRIDE_MINUTES == 15
    assert first["stride_analysis"]["15"]["size_multiplier_vs_v1"] == 1.0
    assert first["stride_analysis"]["5"]["size_multiplier_vs_v1"] == pytest.approx(3.0, rel=0.15)
    assert first["stride_analysis"]["10"]["size_multiplier_vs_v1"] == pytest.approx(1.5, rel=0.15)


def test_same_seed_failure_population_rng_reproduces():
    first = FailurePopulationConfig(enabled=True)
    second = FailurePopulationConfig(enabled=True)
    assert first == second
    from simulator.failure_population import FailurePopulationManager

    a = FailurePopulationManager(first, seed=42)
    b = FailurePopulationManager(second, seed=42)
    assert a.rng.random() == b.rng.random()
    c = FailurePopulationManager(first, seed=43)
    a2 = FailurePopulationManager(first, seed=42)
    assert a2.rng.random() != c.rng.random()
