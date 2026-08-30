"""Zero-cost tests for Failure-Risk V1 dataset spec. No LLM, no database, no training."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.ml.failure_risk.spec import (
    EXCLUDED_FROM_TARGET,
    FORBIDDEN_FEATURE_NAMES,
    HISTORY_LOOKBACK_MINUTES,
    HORIZON_MINUTES,
    MIN_LEAD_TIME_MINUTES,
    STRIDE_MINUTES,
    TELEMETRY_FEATURE_FIELDS,
    UNAVAILABLE_NONBLOCKING_FEATURES,
    VERDICT_FIXES,
    VERDICT_NOT_READY,
    VERDICT_READY,
    FeatureRecord,
    MechanicalIncident,
    ReadinessEvidence,
    assert_no_forbidden_features,
    assign_temporal_splits,
    classify_window,
    do_not_train_for,
    evaluate_readiness,
    filter_history_at_or_before,
    iter_prediction_times,
    labeled_windows,
    merge_mechanical_incidents,
    positive_negative_ratio,
)

T0 = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _incident(
    equipment_id: int,
    start_min: int,
    end_min: int | None = None,
    *,
    incident_id: str | None = None,
) -> MechanicalIncident:
    start = _at(start_min)
    end = None if end_min is None else _at(end_min)
    return MechanicalIncident(
        incident_id=incident_id or f"{equipment_id}:{start.isoformat()}",
        equipment_id=equipment_id,
        start_time=start,
        end_time=end,
    )


def _ready_evidence(**overrides) -> ReadinessEvidence:
    values = dict(
        n_incidents=70,
        n_open_incidents=0,
        n_incidents_with_60min_precursor=70,
        n_positive_windows=200,
        n_negative_windows=2000,
        n_excluded_immediate_pre_failure=40,
        downtime_events=70,
        maintenance_events=70,
        required_feature_max_missing_rate=0.0,
        leakage_feature_violations=0,
        split_incident_leakage=0,
        commission_date_populated=0,
        lead_time_applied=True,
    )
    values.update(overrides)
    return ReadinessEvidence(**values)


def test_v1_horizon_is_60_minutes_not_shorter():
    assert HORIZON_MINUTES == 60
    assert MIN_LEAD_TIME_MINUTES == 15
    assert STRIDE_MINUTES == 15
    assert HISTORY_LOOKBACK_MINUTES == 60
    assert MIN_LEAD_TIME_MINUTES < HORIZON_MINUTES


def test_commission_date_absence_does_not_block_ready():
    result = evaluate_readiness(_ready_evidence(commission_date_populated=0))
    assert result.verdict == VERDICT_READY
    assert result.do_not_train is False
    assert result.reasons["commission_date_missing"] is False
    assert "commission_date" in UNAVAILABLE_NONBLOCKING_FEATURES
    assert "equipment_age" in UNAVAILABLE_NONBLOCKING_FEATURES


def test_ready_to_build_can_be_returned():
    result = evaluate_readiness(_ready_evidence())
    assert result.verdict == VERDICT_READY
    assert result.do_not_train is False
    assert do_not_train_for(result.verdict) is False


def test_zero_incidents_is_not_ready():
    result = evaluate_readiness(_ready_evidence(n_incidents=0, n_incidents_with_60min_precursor=0, n_positive_windows=0))
    assert result.verdict == VERDICT_NOT_READY
    assert result.do_not_train is True
    assert result.reasons["too_few_independent_incidents"] is True


def test_unusable_precursor_coverage_is_not_ready():
    result = evaluate_readiness(
        _ready_evidence(n_incidents=70, n_incidents_with_60min_precursor=10)
    )
    assert result.verdict == VERDICT_NOT_READY
    assert result.do_not_train is True
    assert result.reasons["unusable_precursor_coverage"] is True


def test_manageable_60min_imbalance_can_be_ready():
    result = evaluate_readiness(
        _ready_evidence(n_positive_windows=209, n_negative_windows=2817)
    )
    ratio = positive_negative_ratio(209, 2817)
    assert ratio is not None
    assert 0.05 <= ratio < 0.2
    assert result.verdict == VERDICT_READY
    assert result.reasons["class_imbalance_unusable"] is False


def test_small_incident_count_is_fixes_not_ready_or_full_ready():
    result = evaluate_readiness(_ready_evidence(n_incidents=15, n_incidents_with_60min_precursor=15, downtime_events=15, maintenance_events=15))
    assert result.verdict == VERDICT_FIXES
    assert result.do_not_train is True


def test_do_not_train_matches_readiness_verdict():
    assert do_not_train_for(VERDICT_READY) is False
    assert do_not_train_for(VERDICT_FIXES) is True
    assert do_not_train_for(VERDICT_NOT_READY) is True
    ready = evaluate_readiness(_ready_evidence())
    fixes = evaluate_readiness(_ready_evidence(n_incidents=15, n_incidents_with_60min_precursor=15, downtime_events=15, maintenance_events=15))
    blocked = evaluate_readiness(_ready_evidence(n_incidents=0, n_positive_windows=0))
    assert ready.do_not_train is False
    assert fixes.do_not_train is True
    assert blocked.do_not_train is True


def test_immediate_pre_failure_exclusion_gap_is_enforced():
    incident = _incident(1, start_min=120, end_min=150)
    first_ts = _at(0)
    too_close = classify_window(
        equipment_id=1,
        prediction_time=_at(110),
        incidents=(incident,),
        first_telemetry_ts=first_ts,
    )
    on_gap_boundary = classify_window(
        equipment_id=1,
        prediction_time=_at(105),
        incidents=(incident,),
        first_telemetry_ts=first_ts,
    )
    usable = classify_window(
        equipment_id=1,
        prediction_time=_at(60),
        incidents=(incident,),
        first_telemetry_ts=first_ts,
    )
    assert too_close.exclude_reason == "immediate_pre_failure"
    assert too_close.label is None
    assert too_close.incident_id == incident.incident_id
    assert on_gap_boundary.label == 1
    assert on_gap_boundary.minutes_to_incident == 15.0
    assert usable.label == 1
    assert usable.minutes_to_incident == 60.0


def test_no_feature_timestamp_after_prediction_time():
    records = [
        FeatureRecord(ts=_at(10), name="engine_temp_c", value=90.0),
        FeatureRecord(ts=_at(20), name="engine_temp_c", value=92.0),
        FeatureRecord(ts=_at(31), name="engine_temp_c", value=110.0),
    ]
    kept = filter_history_at_or_before(records, _at(20))
    assert [row.ts for row in kept] == [_at(10), _at(20)]
    assert all(row.ts <= _at(20) for row in kept)


def test_active_failure_windows_are_excluded():
    incident = _incident(1, start_min=120, end_min=150)
    during = classify_window(
        equipment_id=1,
        prediction_time=_at(130),
        incidents=(incident,),
        first_telemetry_ts=_at(0),
    )
    at_start = classify_window(
        equipment_id=1,
        prediction_time=_at(120),
        incidents=(incident,),
        first_telemetry_ts=_at(0),
    )
    after = classify_window(
        equipment_id=1,
        prediction_time=_at(160),
        incidents=(incident,),
        first_telemetry_ts=_at(0),
    )
    assert during.exclude_reason == "active_incident"
    assert at_start.exclude_reason == "active_incident"
    assert after.label == 0
    assert after.exclude_reason is None


def test_one_failure_incident_cannot_leak_across_temporal_splits():
    incidents = tuple(_incident(1, start_min=180 + i * 240, end_min=210 + i * 240) for i in range(6))
    times = list(iter_prediction_times(_at(30), _at(180 + 5 * 240 + 60), stride_minutes=STRIDE_MINUTES))
    windows = labeled_windows(
        equipment_ids=(1,),
        prediction_times=times,
        incidents=incidents,
        first_telemetry_ts={1: _at(0)},
    )
    split = assign_temporal_splits(windows, incidents)
    by_incident: dict[str, set[str]] = {}
    for window in split.train + split.validation + split.test:
        if window.incident_id is None:
            continue
        by_incident.setdefault(window.incident_id, set()).add(window.split)
    assert by_incident
    assert all(len(splits) == 1 for splits in by_incident.values())
    assert split.dropped_boundary_windows >= 0
    train_ids = {w.incident_id for w in split.train if w.incident_id}
    val_ids = {w.incident_id for w in split.validation if w.incident_id}
    test_ids = {w.incident_id for w in split.test if w.incident_id}
    assert train_ids.isdisjoint(val_ids)
    assert train_ids.isdisjoint(test_ids)
    assert val_ids.isdisjoint(test_ids)


def test_forbidden_simulator_fields_remain_excluded():
    for name in (
        "scenario_id",
        "hidden_root_cause",
        "run_id",
        "performance_factor",
        "progress",
        "stage",
        "profile_id",
        "degradation_progress",
        "internal_failure_countdown",
        "seed",
    ):
        assert name in FORBIDDEN_FEATURE_NAMES
        assert name not in TELEMETRY_FEATURE_FIELDS
    assert FORBIDDEN_FEATURE_NAMES.isdisjoint(TELEMETRY_FEATURE_FIELDS)
    assert "commission_date" not in TELEMETRY_FEATURE_FIELDS
    try:
        assert_no_forbidden_features(["engine_temp_c", "hidden_root_cause"])
        raise AssertionError("expected forbidden feature error")
    except ValueError as exc:
        assert "hidden_root_cause" in str(exc)


def test_negative_window_has_no_incident_in_horizon():
    incident = _incident(1, start_min=180, end_min=210)
    far = classify_window(
        equipment_id=1,
        prediction_time=_at(60),
        incidents=(incident,),
        first_telemetry_ts=_at(0),
    )
    assert far.label == 0
    assert far.incident_id is None
    assert far.minutes_to_incident is None


def test_insufficient_history_is_excluded():
    incident = _incident(1, start_min=120, end_min=150)
    window = classify_window(
        equipment_id=1,
        prediction_time=_at(10),
        incidents=(incident,),
        first_telemetry_ts=_at(0),
    )
    assert window.exclude_reason == "insufficient_history"
    assert window.label is None


def test_merge_adjacent_mechanical_intervals():
    rows = [
        {
            "state_id": 1,
            "equipment_id": 7,
            "code": "TRK-001",
            "equipment_type": "TRUCK",
            "start_time": _at(10),
            "end_time": _at(20),
            "reason_code": "MECHANICAL",
        },
        {
            "state_id": 2,
            "equipment_id": 7,
            "code": "TRK-001",
            "equipment_type": "TRUCK",
            "start_time": _at(22),
            "end_time": _at(40),
            "reason_code": "MECHANICAL",
        },
        {
            "state_id": 3,
            "equipment_id": 7,
            "code": "TRK-001",
            "equipment_type": "TRUCK",
            "start_time": _at(80),
            "end_time": _at(100),
            "reason_code": "MECHANICAL",
        },
    ]
    merged = merge_mechanical_incidents(rows)
    assert len(merged) == 2
    assert merged[0].end_time == _at(40)
    assert merged[1].start_time == _at(80)


def test_non_mechanical_states_are_not_in_target():
    assert "STOPPED_UNDEFINED" in EXCLUDED_FROM_TARGET
    assert "NO_DATA" in EXCLUDED_FROM_TARGET
    assert "MAINTENANCE" in EXCLUDED_FROM_TARGET
    assert "STOPPED_EXTERNAL" in EXCLUDED_FROM_TARGET
    assert "STOPPED_MECHANICAL" not in EXCLUDED_FROM_TARGET


def test_empty_downtime_with_incidents_is_not_ready():
    result = evaluate_readiness(_ready_evidence(downtime_events=0))
    assert result.verdict == VERDICT_NOT_READY
    assert result.reasons["downtime_lifecycle_inconsistent"] is True


def test_leakage_violations_block_ready():
    result = evaluate_readiness(_ready_evidence(leakage_feature_violations=1))
    assert result.verdict == VERDICT_NOT_READY
    assert result.do_not_train is True
    assert result.reasons["critical_leakage"] is True


def test_audit_script_uses_spec_readiness_not_hardcoded_do_not_train():
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "audit_failure_risk_dataset.py"
    ).read_text(encoding="utf-8")
    assert "evaluate_readiness" in source
    assert "ReadinessEvidence" in source
    assert '"do_not_train": True' not in source
    assert "from app.ml.failure_risk.spec import" in source
    assert "from simulator" not in source


def test_failure_risk_package_does_not_import_simulator():
    import ast

    root = Path(__file__).resolve().parents[1] / "app" / "ml" / "failure_risk"
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            if any(module == "simulator" or module.startswith("simulator.") for module in modules):
                violations.append(str(path))
    assert violations == []
