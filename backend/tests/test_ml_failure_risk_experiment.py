"""Failure-Risk V1 experiment contracts. No database, no LLM."""

from __future__ import annotations

from pathlib import Path

from app.ml.failure_risk.baselines import FailureRiskBaselines
from app.ml.failure_risk.contracts import MODEL_VERSION, FailureRiskStatus
from app.ml.failure_risk.dataset import build_window_split
from app.ml.failure_risk.experiment import (
    FEATURE_SET_TEMPORAL,
    assert_split_invariants,
    choose_experiment_decision,
    feature_audit,
    freeze_snapshot,
    run_validation_experiment,
    save_versioned_artifact,
    score_held_out_test,
)
from app.ml.failure_risk.features import (
    TEMPORAL_EXTRA_FEATURES,
    build_feature_rows,
    features_for_window,
)
from app.ml.failure_risk.inference import resolve_artifact
from app.ml.failure_risk.model import HGB_DEFAULT_PARAMS, FailureRiskArtifact
from app.ml.failure_risk.spec import FORBIDDEN_FEATURE_NAMES as SPEC_FORBIDDEN
from app.ml.failure_risk.train import persist_artifact, train_from_rows
from test_ml_failure_risk import _balanced_rows, _snapshot, _tel, _window


def test_temporal_extras_are_operational_and_forbidden_free():
    assert SPEC_FORBIDDEN.isdisjoint(TEMPORAL_EXTRA_FEATURES)
    assert SPEC_FORBIDDEN.isdisjoint(FEATURE_SET_TEMPORAL)
    snapshot = _snapshot(end_min=200, incidents=[(180, 210, 1)])
    row = features_for_window(_window(120), snapshot)
    assert row.values["engine_temp_c_min"] is not None
    assert row.values["engine_temp_c_mean_15m"] is not None
    assert "consecutive_abnormal_samples" in row.values
    future = _snapshot(
        end_min=120,
        extra_telemetry=[_tel(1, 150, engine_temp_c=180.0, oil_pressure_kpa=50.0)],
        incidents=[(180, 210, 1)],
    )
    leaked = features_for_window(_window(120), future)
    assert leaked.values["engine_temp_c_latest"] != 180.0


def test_temporal_feature_set_is_available_at_inference_schema_check():
    rows = build_feature_rows(
        [_window(60)],
        _snapshot(end_min=80),
        feature_names=FEATURE_SET_TEMPORAL,
    )
    assert set(TEMPORAL_EXTRA_FEATURES).issubset(rows[0].values)
    assert all(name not in SPEC_FORBIDDEN for name in rows[0].values)


def test_dataset_digest_is_stable_and_ignores_row_object_identity():
    snapshot = _snapshot(end_min=900, incidents=[(180, 210, 1), (420, 450, 1), (660, 690, 1)])
    frozen = freeze_snapshot(snapshot, seed=42, site_id=1)
    again = freeze_snapshot(snapshot, seed=42, site_id=1)
    assert frozen["digest"] == again["digest"]


def test_split_invariants_reject_incident_leakage():
    snapshot = _snapshot(
        end_min=1500,
        incidents=[(180 + i * 240, 210 + i * 240, 1) for i in range(6)],
    )
    split, _exclusions, _incidents = build_window_split(snapshot)
    assert_split_invariants(split)


def test_train_from_rows_can_omit_test_metrics_during_selection():
    rows = _balanced_rows()
    _artifact, report = train_from_rows(
        rows,
        include_test=False,
        hgb_param_grid=(HGB_DEFAULT_PARAMS,),
    )
    assert "served_test" not in report
    assert "hgb_test" not in report
    assert report["selection"]["test_set_used_for_selection"] is False
    assert report["selection"]["test_set_used_for_threshold"] is False
    assert report["selection"]["test_metrics_computed"] is False


def test_validation_experiment_then_held_out_test_is_separate():
    rows = _balanced_rows()
    artifact, report = run_validation_experiment(rows, hgb_param_grid=(HGB_DEFAULT_PARAMS,))
    assert "served_test" not in report
    held_out = score_held_out_test(artifact, rows)
    assert "hgb" in held_out
    assert "logistic" in held_out
    assert "oem_threshold" in held_out
    assert "prevalence" in held_out


def test_same_rows_and_config_train_deterministically():
    rows = _balanced_rows()
    _first, first_report = train_from_rows(rows, include_test=False, hgb_param_grid=(HGB_DEFAULT_PARAMS,))
    _second, second_report = train_from_rows(rows, include_test=False, hgb_param_grid=(HGB_DEFAULT_PARAMS,))
    assert first_report["hgb_validation"]["pr_auc"] == second_report["hgb_validation"]["pr_auc"]
    assert first_report["logistic_validation"]["pr_auc"] == second_report["logistic_validation"]["pr_auc"]


def test_versioned_artifact_does_not_overwrite_canonical_unless_promoted(tmp_path: Path):
    rows = _balanced_rows()
    artifact, _report = train_from_rows(rows, include_test=False, hgb_param_grid=(HGB_DEFAULT_PARAMS,))
    artifact.metadata["dataset_digest"] = "abc123def456"
    paths = save_versioned_artifact(
        artifact, digest="abc123def456", artifacts_root=tmp_path, promote_canonical=False
    )
    assert Path(paths["experiment_joblib"]).is_file()
    assert not (tmp_path / f"{MODEL_VERSION}.joblib").exists()
    save_versioned_artifact(
        artifact, digest="abc123def456", artifacts_root=tmp_path, promote_canonical=True
    )
    assert (tmp_path / f"{MODEL_VERSION}.joblib").is_file()
    metadata = (tmp_path / f"{MODEL_VERSION}.metadata.json").read_text(encoding="utf-8")
    assert "abc123def456" in metadata
    assert "synthetic" in metadata


def test_resolve_artifact_rejects_feature_schema_mismatch(tmp_path: Path):
    artifact = FailureRiskArtifact(
        logistic=None,
        hgb=None,
        baselines=FailureRiskBaselines(prevalence=0.2),
        served_predictor="prevalence",
        threshold=0.5,
        feature_names=("not_a_real_feature",),
    )
    persist_artifact(artifact, tmp_path)
    resolved = resolve_artifact(artifacts_dir=tmp_path)
    assert getattr(resolved, "status", None) == FailureRiskStatus.UNAVAILABLE


def test_promotion_decision_does_not_prefer_tiny_hgb_gains():
    assert (
        choose_experiment_decision(
            served_predictor="logistic",
            ml_promoted=True,
            val_pr_auc={"hgb": 0.41, "logistic": 0.40, "oem_threshold": 0.20},
            test_pr_auc={"hgb": 0.39, "logistic": 0.38},
            robustness=None,
        )
        == "LOGISTIC_PROMOTED"
    )
    assert (
        choose_experiment_decision(
            served_predictor="oem_threshold",
            ml_promoted=False,
            val_pr_auc={"hgb": 0.21, "logistic": 0.20, "oem_threshold": 0.22},
            test_pr_auc={"hgb": 0.20, "logistic": 0.19},
            robustness=None,
        )
        == "BASELINE_RETAINED"
    )
    assert (
        choose_experiment_decision(
            served_predictor="hgb",
            ml_promoted=True,
            val_pr_auc={"hgb": 0.80, "logistic": 0.20, "oem_threshold": 0.22},
            test_pr_auc={"hgb": 0.10, "logistic": 0.18},
            robustness=None,
        )
        == "NO_MODEL_READY"
    )


def test_feature_audit_flags_near_constant_and_not_hidden_truth():
    rows = _balanced_rows()
    audit = feature_audit(rows)
    assert audit["forbidden_in_schema"] == []
    names = {item["feature"] for item in audit["profiles"]}
    assert "engine_temp_c_latest" in names
    assert "scenario_id" not in names
