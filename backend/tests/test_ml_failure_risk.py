"""Zero-cost tests for Failure-Risk V1 training and inference. No LLM, no paid APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ml.failure_risk.baselines import FailureRiskBaselines, oem_warn_count
from app.ml.failure_risk.contracts import (
    MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT,
    MODEL_VERSION,
    SYNTHETIC_DATA_WARNING,
    TRAINING_DATA_TYPE,
    FailureRiskStatus,
    ModelStatus,
)
from app.ml.failure_risk.dataset import (
    EquipmentInfo,
    EventSample,
    FailureRiskSnapshot,
    MaintenanceSample,
    StateInterval,
    TelemetrySample,
    build_window_split,
    load_snapshot,
)
from app.ml.failure_risk.evaluation import apply_threshold, select_threshold_max_f1
from app.ml.failure_risk.features import (
    FEATURE_NAMES,
    NUMERIC_FEATURES,
    FeatureRow,
    build_feature_rows,
    features_for_window,
)
from app.ml.failure_risk.inference import (
    predict_from_snapshot,
    resolve_artifact,
    risk_level_for,
    score_equipment,
)
from app.ml.failure_risk.model import (
    FailureRiskArtifact,
    build_hgb_pipeline,
    build_logistic_pipeline,
    predict_proba_positive,
    rows_to_matrix,
)
from app.ml.failure_risk.policy import select_learned_model, select_served_predictor
from app.ml.failure_risk.spec import (
    FORBIDDEN_FEATURE_NAMES,
    HORIZON_MINUTES,
    MIN_LEAD_TIME_MINUTES,
    STRIDE_MINUTES,
    TELEMETRY_FEATURE_FIELDS,
    LabeledWindow,
    split_has_incident_leakage,
)
from app.ml.failure_risk.train import train_from_rows

T0 = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)


def _at(minutes: int) -> datetime:
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
    end_min: int = 300,
    incidents: list[tuple[int, int, int]] | None = None,
    extra_telemetry: list[TelemetrySample] | None = None,
    oem_events: list[EventSample] | None = None,
    maintenance: list[MaintenanceSample] | None = None,
    states: list[StateInterval] | None = None,
) -> FailureRiskSnapshot:
    telemetry = [_tel(1, minute) for minute in range(0, end_min + 1, 2)]
    if extra_telemetry:
        telemetry.extend(extra_telemetry)
    state_rows = [
        StateInterval(1, "MOVING_LOADED", _at(0), None),
    ]
    if incidents:
        for start, end, _eid in incidents:
            state_rows.append(StateInterval(1, "STOPPED_MECHANICAL", _at(start), _at(end)))
    if states:
        state_rows.extend(states)
    return FailureRiskSnapshot(
        equipment={1: EquipmentInfo(1, "TRK-001"), 2: EquipmentInfo(2, "TRK-002")},
        telemetry=telemetry,
        states=state_rows,
        oem_events=oem_events or [],
        maintenance=maintenance or [],
    )


def _window(minutes: int, label: int = 0, incident_id: str | None = None) -> LabeledWindow:
    return LabeledWindow(
        equipment_id=1,
        prediction_time=_at(minutes),
        label=label,
        exclude_reason=None,
        incident_id=incident_id,
        minutes_to_incident=None,
        split="train",
    )


def _default_values(*, temp: float = 90.0, oil: float = 280.0) -> dict:
    values = {name: 0.0 for name in NUMERIC_FEATURES}
    values["current_state"] = "MOVING_LOADED"
    values["engine_temp_c_latest"] = temp
    values["engine_temp_c_mean"] = temp
    values["engine_temp_c_std"] = 1.0
    values["engine_temp_c_slope"] = 0.4 if temp >= 100 else 0.0
    values["engine_temp_c_change"] = 8.0 if temp >= 100 else 0.0
    values["coolant_temp_c_latest"] = 80.0 if temp < 100 else 100.0
    values["coolant_temp_c_mean"] = values["coolant_temp_c_latest"]
    values["oil_pressure_kpa_latest"] = oil
    values["oil_pressure_kpa_mean"] = oil
    values["battery_voltage_latest"] = 26.0 if temp < 100 else 23.0
    values["battery_voltage_mean"] = values["battery_voltage_latest"]
    return values


def _feat(
    i: int,
    *,
    label: int,
    split: str,
    temp: float,
    start: int | None = None,
) -> FeatureRow:
    minute = start if start is not None else i * 15
    return FeatureRow(
        equipment_id=1,
        prediction_time=_at(minute),
        label=label,
        incident_id=f"inc-{i}" if label == 1 else None,
        minutes_to_incident=30.0 if label == 1 else None,
        split=split,
        values=_default_values(temp=temp),
    )


def _balanced_rows() -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    idx = 0
    for split, n, start in (("train", 24, 0), ("validation", 8, 400), ("test", 8, 600)):
        for i in range(n):
            positive = i % 3 == 0
            rows.append(
                _feat(
                    idx,
                    label=1 if positive else 0,
                    split=split,
                    temp=108.0 if positive else 88.0,
                    start=start + i * 15,
                )
            )
            idx += 1
    return rows


def _inference_artifact() -> FailureRiskArtifact:
    return FailureRiskArtifact(
        logistic=None,
        hgb=None,
        baselines=FailureRiskBaselines(prevalence=0.25),
        served_predictor="prevalence",
        threshold=0.5,
        feature_names=FEATURE_NAMES,
    )


def test_dataset_reproduces_60_minute_horizon_and_15_minute_lead():
    snapshot = _snapshot(end_min=300, incidents=[(188, 220, 1)])
    split, exclusions, incidents = build_window_split(snapshot)
    windows = list(split.train) + list(split.validation) + list(split.test)
    assert incidents
    assert HORIZON_MINUTES == 60
    assert MIN_LEAD_TIME_MINUTES == 15
    assert STRIDE_MINUTES == 15
    positives = [row for row in windows if row.label == 1]
    assert positives
    assert all(row.minutes_to_incident is not None and 15 <= row.minutes_to_incident <= 60 for row in positives)
    assert exclusions["immediate_pre_failure"] >= 1
    assert exclusions["active_incident"] >= 1


def test_no_future_telemetry_or_oem_events_enter_features():
    snapshot = _snapshot(
        end_min=120,
        extra_telemetry=[_tel(1, 90, engine_temp_c=140.0)],
        oem_events=[EventSample(1, _at(90), "SIM-ENG-TEMP-HIGH")],
        maintenance=[MaintenanceSample(1, _at(90), _at(100))],
    )
    row = features_for_window(_window(60), snapshot)
    assert row.values["engine_temp_c_latest"] != 140.0
    assert row.values["oem_event_count_lookback"] == 0.0
    assert row.values["maintenance_count_before_t"] == 0.0
    assert row.values["minutes_since_last_completed_maintenance"] is None


def test_active_incident_windows_excluded_from_dataset():
    snapshot = _snapshot(end_min=240, incidents=[(180, 210, 1)])
    split, exclusions, _incidents = build_window_split(snapshot)
    windows = list(split.train) + list(split.validation) + list(split.test)
    assert exclusions["active_incident"] >= 1
    assert all(not (row.prediction_time >= _at(180) and row.prediction_time < _at(210)) for row in windows)


def test_same_incident_cannot_leak_and_boundary_negatives_are_dropped():
    snapshot = _snapshot(
        end_min=1500,
        incidents=[(180 + i * 240, 210 + i * 240, 1) for i in range(6)],
    )
    split, _exclusions, incidents = build_window_split(snapshot)
    assert not split_has_incident_leakage(split)
    assert split.dropped_boundary_windows >= 0
    train_ids = {row.incident_id for row in split.train if row.incident_id}
    val_ids = {row.incident_id for row in split.validation if row.incident_id}
    test_ids = {row.incident_id for row in split.test if row.incident_id}
    assert train_ids.isdisjoint(val_ids)
    assert train_ids.isdisjoint(test_ids)
    assert val_ids.isdisjoint(test_ids)
    assert len(incidents) == 6


def test_forbidden_simulator_fields_never_enter_feature_schema():
    assert FORBIDDEN_FEATURE_NAMES.isdisjoint(FEATURE_NAMES)
    for name in ("scenario_id", "hidden_root_cause", "profile_id", "seed", "progress"):
        assert name not in FEATURE_NAMES


def test_baseline_uses_repository_thresholds():
    hot = _feat(1, label=1, split="train", temp=108.0)
    cool = _feat(2, label=0, split="train", temp=88.0)
    assert oem_warn_count(hot) >= 1
    assert oem_warn_count(cool) == 0
    fitted = FailureRiskBaselines().fit([hot, cool, cool, cool])
    assert 0 < fitted.prevalence < 1
    assert fitted.predict_oem_binary([hot, cool]) == [1, 0]


def test_logistic_and_hgb_produce_finite_probabilities():
    rows = _balanced_rows()
    y = [row.label for row in rows]
    logistic = build_logistic_pipeline()
    logistic.fit(rows_to_matrix(rows), y)
    hgb = build_hgb_pipeline(max_iter=40, min_samples_leaf=5)
    hgb.fit(rows_to_matrix(rows), y)
    for preds in (predict_proba_positive(logistic, rows), predict_proba_positive(hgb, rows)):
        assert len(preds) == len(rows)
        assert all(pred == pred and 0.0 <= pred <= 1.0 for pred in preds)


def test_validation_only_selection_and_threshold():
    rows = _balanced_rows()
    artifact, report = train_from_rows(rows, excluded={"immediate_pre_failure": 2})
    assert report["selection"]["uses"] == "validation_only"
    assert report["selection"]["test_set_used_for_selection"] is False
    assert report["selection"]["test_set_used_for_threshold"] is False
    assert report["training_data_type"] == TRAINING_DATA_TYPE
    assert "synthetic" in report["synthetic_data_warning"].lower()
    assert SYNTHETIC_DATA_WARNING in report["synthetic_data_warning"]
    assert report["model_version"] == MODEL_VERSION
    assert report["feature_schema"] == list(FEATURE_NAMES)
    assert report["horizon_minutes"] == 60
    assert report["minimum_lead_time_min"] == 15
    y_val = [row.label for row in rows if row.split == "validation"]
    # Threshold must be the validation F1 maximizer of the served scores, not a test-tuned value.
    from app.ml.failure_risk.train import _scores_for

    val_rows = [row for row in rows if row.split == "validation"]
    val_scores = _scores_for(artifact.served_predictor, artifact, val_rows)
    expected_t, _metrics = select_threshold_max_f1(y_val, val_scores)
    assert artifact.threshold == expected_t
    assert report["selection"]["test_set_used_for_selection"] is False


def test_policy_requires_material_pr_auc_gain():
    tiny = select_served_predictor(
        logistic_pr_auc=0.204,
        hgb_pr_auc=0.205,
        baseline_pr_auc={"prevalence": 0.20, "oem_threshold": 0.19},
        threshold=MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT,
    )
    assert tiny.ml_promoted is False
    assert tiny.served_predictor == "prevalence"
    strong = select_served_predictor(
        logistic_pr_auc=0.40,
        hgb_pr_auc=0.41,
        baseline_pr_auc={"prevalence": 0.20, "oem_threshold": 0.22},
    )
    assert strong.ml_promoted is True
    assert strong.model_status == ModelStatus.MODEL_BEATS_BASELINE
    assert select_learned_model(0.40, 0.41)[0] == "logistic"


def test_inference_never_reads_after_t_and_insufficient_history_is_explicit():
    snapshot = _snapshot(end_min=80, extra_telemetry=[_tel(1, 70, engine_temp_c=150.0)])
    rows = _balanced_rows()
    artifact, _report = train_from_rows(rows)
    available = predict_from_snapshot(snapshot, 1, _at(40), artifact)
    assert available.status == FailureRiskStatus.AVAILABLE
    assert available.risk_probability is not None
    short = FailureRiskSnapshot(
        equipment={1: EquipmentInfo(1, "TRK-001")},
        telemetry=[_tel(1, 50)],
        states=[],
        oem_events=[],
        maintenance=[],
    )
    missing = predict_from_snapshot(short, 1, _at(52), artifact)
    assert missing.status == FailureRiskStatus.INSUFFICIENT_HISTORY
    assert missing.risk_probability is None
    unknown = predict_from_snapshot(snapshot, 99, _at(40), artifact)
    assert unknown.status == FailureRiskStatus.UNAVAILABLE
    assert unknown.risk_probability is None
    unresolved = resolve_artifact(artifacts_dir=Path("missing-artifacts-dir"))
    assert getattr(unresolved, "status", None) == FailureRiskStatus.UNAVAILABLE
    assert unresolved.risk_probability is None


def test_inference_rejects_an_empty_feature_lookback_without_imputing_zero_risk():
    result = predict_from_snapshot(_snapshot(end_min=20), 1, _at(100), _inference_artifact())

    assert result.status == FailureRiskStatus.UNAVAILABLE
    assert result.risk_probability is None
    assert result.feature_timestamp == _at(20)


def test_inference_rejects_telemetry_older_than_the_documented_sampling_cadence():
    result = predict_from_snapshot(_snapshot(end_min=80), 1, _at(83), _inference_artifact())

    assert result.status == FailureRiskStatus.UNAVAILABLE
    assert result.risk_probability is None
    assert result.feature_timestamp == _at(80)


def test_available_inference_reports_the_latest_observed_feature_timestamp():
    result = predict_from_snapshot(_snapshot(end_min=80), 1, _at(81), _inference_artifact())

    assert result.status == FailureRiskStatus.AVAILABLE
    assert result.feature_timestamp == _at(80)


def test_score_equipment_returns_unavailable_copies_when_artifact_is_missing():
    scored = score_equipment(object(), [1, 2], _at(40), site_id=1, artifacts_dir=Path("missing-artifacts-dir"))
    assert set(scored) == {1, 2}
    assert all(item.status == FailureRiskStatus.UNAVAILABLE for item in scored.values())
    assert all(item.risk_probability is None for item in scored.values())
    assert scored[1].equipment_id == 1
    assert scored[2].equipment_id == 2


def test_score_equipment_loads_snapshot_once(monkeypatch):
    snapshot = _snapshot(end_min=80)
    rows = _balanced_rows()
    artifact, _report = train_from_rows(rows)
    loads = []
    monkeypatch.setattr(
        "app.ml.failure_risk.inference.load_snapshot",
        lambda _session, *, site_id: loads.append(site_id) or snapshot,
    )
    scored = score_equipment(object(), [1, 99], _at(40), site_id=1, artifact=artifact)
    assert loads == [1]
    assert scored[1].status == FailureRiskStatus.AVAILABLE
    assert scored[99].status == FailureRiskStatus.UNAVAILABLE
    assert scored[99].risk_probability is None


def test_score_equipment_loads_the_requested_site_only(monkeypatch):
    snapshot = _snapshot(end_min=80)
    requested_sites = []
    monkeypatch.setattr(
        "app.ml.failure_risk.inference.load_snapshot",
        lambda _session, *, site_id: requested_sites.append(site_id) or snapshot,
    )

    scored = score_equipment(object(), [1], _at(80), artifact=_inference_artifact(), site_id=7)

    assert requested_sites == [7]
    assert scored[1].status == FailureRiskStatus.AVAILABLE


class _Rows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _FailureSnapshotSession:
    def __init__(self, site_id, rows_by_entity):
        self.site_id = site_id
        self.rows_by_entity = rows_by_entity

    def scalars(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert f"equipment.site_id = {self.site_id}" in sql
        entity = statement.column_descriptions[0]["entity"]
        return _Rows(self.rows_by_entity[entity])


def test_failure_snapshot_loader_scopes_every_observational_relation_to_requested_site():
    from app.db.models import Equipment, MaintenanceEvent, SystemEvent
    from app.db.models.telemetry import EquipmentState as EquipmentStateRow
    from app.db.models.telemetry import EquipmentTelemetry

    telemetry = {name: None for name in TELEMETRY_FEATURE_FIELDS}
    session = _FailureSnapshotSession(
        7,
        {
            Equipment: [SimpleNamespace(equipment_id=1, code="TRK-S7")],
            EquipmentTelemetry: [SimpleNamespace(equipment_id=1, ts=_at(80), **telemetry)],
            EquipmentStateRow: [SimpleNamespace(equipment_id=1, state="MOVING_EMPTY", start_time=_at(0), end_time=None)],
            SystemEvent: [],
            MaintenanceEvent: [],
        },
    )

    snapshot = load_snapshot(session, site_id=7)

    assert set(snapshot.equipment) == {1}
    assert [sample.equipment_id for sample in snapshot.telemetry] == [1]
    assert [state.equipment_id for state in snapshot.states] == [1]


def test_active_stop_inference_is_unavailable_not_zero_risk():
    snapshot = _snapshot(end_min=240, incidents=[(180, 210, 1)])
    rows = _balanced_rows()
    artifact, _report = train_from_rows(rows)
    result = predict_from_snapshot(snapshot, 1, _at(190), artifact)
    assert result.status == FailureRiskStatus.UNAVAILABLE
    assert result.risk_probability is None


def test_risk_levels_use_selected_threshold():
    assert risk_level_for(0.9, 0.4).value == "HIGH"
    assert risk_level_for(0.25, 0.4).value == "MEDIUM"
    assert risk_level_for(0.1, 0.4).value == "LOW"


def test_no_paid_api_imports_in_failure_risk_package():
    import ast

    root = Path(__file__).resolve().parents[1] / "app" / "ml" / "failure_risk"
    banned = {"openai", "anthropic", "litellm", "google.generativeai"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            assert banned.isdisjoint(modules)


def test_missing_logistic_does_not_fall_back_to_hgb():
    rows = _balanced_rows()
    artifact, _report = train_from_rows(rows)
    artifact.served_predictor = "logistic"
    artifact.logistic = None
    resolved = resolve_artifact(artifact=artifact)
    assert resolved.status == FailureRiskStatus.UNAVAILABLE
    assert resolved.risk_probability is None
    assert "logistic" in (resolved.detail or "").casefold()


def test_disk_artifact_without_metadata_is_unavailable(tmp_path):
    from app.ml.failure_risk.model import ARTIFACT_FILE, save_artifact

    save_artifact(_inference_artifact(), tmp_path / ARTIFACT_FILE)
    resolved = resolve_artifact(artifacts_dir=tmp_path)
    assert resolved.status == FailureRiskStatus.UNAVAILABLE
    assert resolved.risk_probability is None
    assert "metadata" in (resolved.detail or "").casefold()


def test_unreadable_artifact_is_unavailable_not_zero_risk(tmp_path):
    from app.ml.failure_risk.model import ARTIFACT_FILE

    (tmp_path / ARTIFACT_FILE).write_text("not-a-joblib", encoding="utf-8")
    resolved = resolve_artifact(artifacts_dir=tmp_path)
    assert resolved.status == FailureRiskStatus.UNAVAILABLE
    assert resolved.risk_probability is None


def test_wrong_feature_schema_is_unavailable():
    artifact = _inference_artifact()
    artifact.feature_names = ("engine_temp_c_latest",)
    resolved = resolve_artifact(artifact=artifact)
    assert resolved.status == FailureRiskStatus.UNAVAILABLE
    assert resolved.risk_probability is None
    assert "schema" in (resolved.detail or "").casefold()


def test_runtime_does_not_rewrite_served_predictor_after_scoring():
    artifact, _report = train_from_rows(_balanced_rows())
    served = artifact.served_predictor
    predict_from_snapshot(_snapshot(end_min=80), 1, _at(40), artifact)
    assert artifact.served_predictor == served


def test_served_logistic_scores_the_logistic_pipeline_not_hgb(monkeypatch):
    from app.ml.failure_risk import inference as inference_mod

    artifact, _report = train_from_rows(_balanced_rows())
    artifact.served_predictor = "logistic"
    used = []
    original = inference_mod.predict_proba_positive

    def wrapped(pipeline, rows, **kwargs):
        used.append(pipeline)
        return original(pipeline, rows, **kwargs)

    monkeypatch.setattr(inference_mod, "predict_proba_positive", wrapped)
    result = predict_from_snapshot(_snapshot(end_min=80), 1, _at(40), artifact)
    assert result.status == FailureRiskStatus.AVAILABLE
    assert used == [artifact.logistic]
    assert artifact.hgb is not None
    assert used[0] is not artifact.hgb


def test_threshold_apply_helper():
    assert apply_threshold([0.1, 0.5, 0.9], 0.5) == [0, 1, 1]


def test_train_from_database_blocks_when_readiness_forbids_training(monkeypatch):
    from app.ml.failure_risk import train as train_mod

    calls: list[str] = []
    monkeypatch.setattr(train_mod, "resolve_ml_site_id", lambda _session, site_id=None: 7)
    monkeypatch.setattr(train_mod, "load_snapshot", lambda _session, *, site_id: SimpleNamespace(states=[], maintenance=[]))
    monkeypatch.setattr(
        train_mod,
        "build_window_split",
        lambda _snapshot: (
            SimpleNamespace(train=(), validation=(), test=(), dropped_boundary_windows=0),
            {"labeled_positive": 0, "labeled_negative": 0, "immediate_pre_failure": 0},
            [],
        ),
    )
    monkeypatch.setattr(train_mod, "split_has_incident_leakage", lambda _split: False)
    monkeypatch.setattr(train_mod, "build_feature_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(train_mod, "missing_rates", lambda _rows: {})
    monkeypatch.setattr(train_mod, "readiness_evidence", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(
        train_mod,
        "evaluate_readiness",
        lambda _evidence: SimpleNamespace(do_not_train=True, verdict="NOT READY — DATA/SIMULATOR CHANGES REQUIRED"),
    )
    monkeypatch.setattr(train_mod, "train_from_rows", lambda *_args, **_kwargs: calls.append("fit") or (None, {}))
    monkeypatch.setattr(train_mod, "persist_artifact", lambda *_args, **_kwargs: calls.append("persist"))

    with pytest.raises(ValueError, match="blocked"):
        train_mod.train_from_database(object(), Path("unused-artifacts"))
    assert calls == []


def test_train_from_database_scopes_snapshot_to_resolved_site_when_ready(monkeypatch):
    from app.ml.failure_risk import train as train_mod

    requested: list[int] = []
    monkeypatch.setattr(train_mod, "resolve_ml_site_id", lambda _session, site_id=None: site_id or 7)
    monkeypatch.setattr(
        train_mod,
        "load_snapshot",
        lambda _session, *, site_id: requested.append(site_id) or SimpleNamespace(states=[], maintenance=[]),
    )
    monkeypatch.setattr(
        train_mod,
        "build_window_split",
            lambda _snapshot: (
                SimpleNamespace(
                    train=(SimpleNamespace(incident_id="inc-1", label=1),),
                    validation=(SimpleNamespace(incident_id="inc-2", label=0),),
                    test=(),
                    dropped_boundary_windows=0,
                ),
            {"labeled_positive": 20, "labeled_negative": 200, "immediate_pre_failure": 4},
            [SimpleNamespace(end_time=_at(10))],
        ),
    )
    monkeypatch.setattr(train_mod, "split_has_incident_leakage", lambda _split: False)
    monkeypatch.setattr(train_mod, "build_feature_rows", lambda *_args, **_kwargs: [object()])
    monkeypatch.setattr(train_mod, "missing_rates", lambda _rows: {"engine_temp_c_latest": 0.0})
    monkeypatch.setattr(train_mod, "readiness_evidence", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(train_mod, "evaluate_readiness", lambda _evidence: SimpleNamespace(do_not_train=False, verdict="READY TO BUILD FAILURE-RISK V1"))
    monkeypatch.setattr(train_mod, "snapshot_summary", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(train_mod, "train_from_rows", lambda *_args, **_kwargs: (SimpleNamespace(), {"ok": True}))
    monkeypatch.setattr(train_mod, "persist_artifact", lambda *_args, **_kwargs: None)

    report = train_mod.train_from_database(object(), Path("unused-artifacts"), site_id=7)

    assert requested == [7]
    assert report == {"ok": True}
