"""Failure-Risk V1 experiment helpers: freeze, audit, ablation, thresholds.

Does not train on the configured MinePulse database. Callers must pass a
disposable snapshot. Test metrics are computed only when explicitly requested.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any, Sequence

from sklearn.calibration import calibration_curve
from sklearn.inspection import permutation_importance
from sklearn.metrics import brier_score_loss

from app.ml.failure_risk.contracts import (
    MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT,
    MODEL_VERSION,
    TRAINING_DATA_TYPE,
)
from app.ml.failure_risk.dataset import (
    FailureRiskSnapshot,
    build_window_split,
    readiness_evidence,
    snapshot_summary,
    telemetry_span,
)
from app.ml.failure_risk.evaluation import (
    apply_threshold,
    classification_report,
    labels_of,
    operational_metrics,
    ranking_metrics,
    relative_pr_auc_improvement,
    select_threshold_max_f1,
)
from app.ml.failure_risk.features import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    FEATURE_VERSION,
    TEMPORAL_EXTRA_FEATURES,
    FeatureRow,
    build_feature_rows,
    missing_rates,
)
from app.ml.failure_risk.model import (
    HGB_DEFAULT_PARAMS,
    FailureRiskArtifact,
    rows_to_matrix,
    schema_indexes,
)
from app.ml.failure_risk.spec import (
    FORBIDDEN_FEATURE_NAMES,
    HORIZON_MINUTES,
    evaluate_readiness,
    required_telemetry_missing_rate,
    split_has_incident_leakage,
)
from app.ml.failure_risk.train import _scores_for, persist_artifact, train_from_rows

FEATURE_SET_V1 = FEATURE_NAMES
FEATURE_SET_TEMPORAL = FEATURE_NAMES + TEMPORAL_EXTRA_FEATURES
NEAR_CONSTANT_STD = 1e-9
THRESHOLD_CANDIDATES = (0.25, 0.35, 0.45, 0.5, 0.55, 0.65, 0.75)


class SplitInvariantError(ValueError):
    """Raised when leakage-safe split rules fail before training."""


def git_commit(repo_root: Path | None = None) -> str | None:
    root = repo_root or Path(__file__).resolve().parents[4]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def dataset_digest(rows: Sequence[FeatureRow], *, extra: dict[str, Any] | None = None) -> str:
    payload = {
        "windows": [
            {
                "equipment_id": row.equipment_id,
                "prediction_time": row.prediction_time.isoformat(),
                "label": row.label,
                "incident_id": row.incident_id,
                "split": row.split,
                "minutes_to_incident": row.minutes_to_incident,
            }
            for row in sorted(
                rows,
                key=lambda item: (
                    item.split or "",
                    item.prediction_time.isoformat(),
                    item.equipment_id,
                    item.incident_id or "",
                ),
            )
        ],
        "extra": extra or {},
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_split_invariants(split) -> None:
    if split_has_incident_leakage(split):
        raise SplitInvariantError("Incident leakage across temporal splits.")
    owners: dict[str, set[str]] = {}
    for name, rows in (
        ("train", split.train),
        ("validation", split.validation),
        ("test", split.test),
    ):
        for window in rows:
            if window.incident_id:
                owners.setdefault(window.incident_id, set()).add(name)
    if any(len(names) > 1 for names in owners.values()):
        raise SplitInvariantError("One incident belongs to multiple splits.")
    nonempty = [
        (name, rows)
        for name, rows in (
            ("train", split.train),
            ("validation", split.validation),
            ("test", split.test),
        )
        if rows
    ]
    for (_left_name, left), (_right_name, right) in zip(nonempty, nonempty[1:]):
        if max(row.prediction_time for row in left) >= min(row.prediction_time for row in right):
            raise SplitInvariantError("Temporal partitions are not strictly ordered.")
    horizon = timedelta(minutes=HORIZON_MINUTES)
    first_val = min((row.prediction_time for row in split.validation), default=None)
    first_test = min((row.prediction_time for row in split.test), default=None)
    for row in split.train:
        if row.label == 0 and first_val is not None and row.prediction_time < first_val < row.prediction_time + horizon:
            raise SplitInvariantError("Train negative horizon crosses the validation boundary.")
    for row in split.validation:
        if row.label == 0 and first_test is not None and row.prediction_time < first_test < row.prediction_time + horizon:
            raise SplitInvariantError("Validation negative horizon crosses the test boundary.")
    if FORBIDDEN_FEATURE_NAMES.intersection(FEATURE_NAMES):
        raise SplitInvariantError("Forbidden simulator fields are in the feature schema.")


def freeze_snapshot(
    snapshot: FailureRiskSnapshot,
    *,
    seed: int,
    site_id: int,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> dict[str, Any]:
    split, exclusions, incidents = build_window_split(snapshot)
    assert_split_invariants(split)
    windows = list(split.train) + list(split.validation) + list(split.test)
    rows = build_feature_rows(windows, snapshot, feature_names=feature_names)
    rates = missing_rates(rows, feature_names=feature_names)
    evidence = readiness_evidence(
        snapshot,
        split,
        exclusions,
        incidents,
        missing_rate_max=required_telemetry_missing_rate(rates),
        leakage_feature_violations=len([name for name in feature_names if name in FORBIDDEN_FEATURE_NAMES]),
    )
    readiness = evaluate_readiness(evidence)
    data_start, data_end, _first = telemetry_span(snapshot)
    extra = {
        "seed": seed,
        "site_id": site_id,
        "feature_names": list(feature_names),
        "feature_version": FEATURE_VERSION,
        "n_incidents": len(incidents),
        "equipment": len(snapshot.equipment),
        "telemetry_rows": len(snapshot.telemetry),
    }
    digest = dataset_digest(rows, extra=extra)
    summary = snapshot_summary(snapshot, split, exclusions)
    return {
        "digest": digest,
        "seed": seed,
        "site_id": site_id,
        "git_commit": git_commit(),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_names": list(feature_names),
        "training_data_type": TRAINING_DATA_TYPE,
        "equipment_count": len(snapshot.equipment),
        "telemetry_rows": len(snapshot.telemetry),
        "mechanical_incident_count": len(incidents),
        "positive_windows": int(exclusions.get("labeled_positive", 0)),
        "negative_windows": int(exclusions.get("labeled_negative", 0)),
        "excluded_windows": {
            key: value
            for key, value in exclusions.items()
            if key not in {"labeled_positive", "labeled_negative"}
        },
        "data_start": data_start.isoformat() if data_start else None,
        "data_end": data_end.isoformat() if data_end else None,
        "missing_rates_pct": rates,
        "readiness_verdict": readiness.verdict,
        "do_not_train": readiness.do_not_train,
        "readiness_reasons": readiness.reasons,
        "n_incidents_with_60min_precursor": evidence.n_incidents_with_60min_precursor,
        "split_summary": summary.get("split_counts"),
        "dropped_boundary_windows": split.dropped_boundary_windows,
        "rows": rows,
        "split": split,
        "exclusions": exclusions,
        "incidents": incidents,
        "snapshot_summary": summary,
    }


def feature_audit(rows: Sequence[FeatureRow], *, feature_names: tuple[str, ...] = FEATURE_NAMES) -> dict[str, Any]:
    n = len(rows)
    profiles: list[dict[str, Any]] = []
    near_constant: list[str] = []
    for name in feature_names:
        values = [row.values.get(name) for row in rows]
        if name in CATEGORICAL_FEATURES:
            present = [str(value) for value in values if value is not None]
            unique = sorted(set(present))
            missing = round(100.0 * (n - len(present)) / n, 1) if n else 0.0
            profiles.append(
                {
                    "feature": name,
                    "kind": "categorical",
                    "missing_pct": missing,
                    "n_unique": len(unique),
                    "near_constant": len(unique) <= 1,
                    "leakage_risk": name in FORBIDDEN_FEATURE_NAMES,
                }
            )
            if len(unique) <= 1:
                near_constant.append(name)
            continue
        numeric = [float(value) for value in values if value is not None]
        missing = round(100.0 * (n - len(numeric)) / n, 1) if n else 0.0
        std = statistics.pstdev(numeric) if len(numeric) >= 2 else 0.0
        mean = statistics.mean(numeric) if numeric else None
        profiles.append(
            {
                "feature": name,
                "kind": "numeric",
                "missing_pct": missing,
                "mean": None if mean is None else round(mean, 4),
                "std": round(std, 6),
                "min": None if not numeric else round(min(numeric), 4),
                "max": None if not numeric else round(max(numeric), 4),
                "near_constant": std <= NEAR_CONSTANT_STD,
                "leakage_risk": name in FORBIDDEN_FEATURE_NAMES,
            }
        )
        if std <= NEAR_CONSTANT_STD:
            near_constant.append(name)
    return {
        "n_rows": n,
        "near_constant_features": near_constant,
        "forbidden_in_schema": sorted(FORBIDDEN_FEATURE_NAMES.intersection(feature_names)),
        "profiles": profiles,
    }


def permutation_ranks(
    artifact: FailureRiskArtifact,
    rows: list[FeatureRow],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    n_repeats: int = 5,
) -> list[dict[str, float | str]]:
    if artifact.hgb is None or not rows:
        return []
    matrix = rows_to_matrix(rows, feature_names=feature_names)
    y = labels_of(rows)
    result = permutation_importance(
        artifact.hgb,
        matrix,
        y,
        n_repeats=n_repeats,
        random_state=42,
        scoring="average_precision",
    )
    cats, nums, _cat_idx, _num_idx = schema_indexes(feature_names)
    raw_names = list(cats) + list(nums)
    ranked = sorted(
        zip(raw_names, result.importances_mean, result.importances_std),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        {"feature": name, "importance_mean": round(float(mean), 6), "importance_std": round(float(std), 6)}
        for name, mean, std in ranked
    ]


def calibration_summary(y_true: list[int], scores: list[float]) -> dict[str, Any]:
    if len(set(y_true)) < 2:
        return {"brier": None, "bins": []}
    brier = round(float(brier_score_loss(y_true, [min(1.0, max(0.0, score)) for score in scores])), 4)
    try:
        frac_pos, mean_pred = calibration_curve(y_true, scores, n_bins=min(8, len(y_true)), strategy="quantile")
    except ValueError:
        return {"brier": brier, "bins": []}
    bins = [
        {"mean_predicted": round(float(pred), 4), "fraction_positive": round(float(frac), 4)}
        for pred, frac in zip(mean_pred, frac_pos)
    ]
    return {"brier": brier, "bins": bins}


def threshold_tradeoffs(
    rows: list[FeatureRow],
    scores: list[float],
    *,
    selected: float,
) -> dict[str, Any]:
    y_true = labels_of(rows)
    table: list[dict[str, Any]] = []
    for threshold in THRESHOLD_CANDIDATES:
        report = classification_report(y_true, scores, threshold)
        ops = operational_metrics(rows, apply_threshold(scores, threshold))
        table.append({"threshold": threshold, **report, **ops})
    f1_threshold, f1_metrics = select_threshold_max_f1(y_true, scores)
    f1_ops = operational_metrics(rows, apply_threshold(scores, f1_threshold))
    return {
        "selected_threshold": selected,
        "f1_max_threshold": f1_threshold,
        "f1_max_operating": {**f1_metrics, **f1_ops},
        "candidates": table,
        "rule": (
            "Operating threshold maximizes validation F1. Candidate table is reported "
            "for recall vs false-alarm trade-offs; the test set is not used."
        ),
    }


def choose_experiment_decision(
    *,
    served_predictor: str,
    ml_promoted: bool,
    val_pr_auc: dict[str, float | None],
    test_pr_auc: dict[str, float | None],
    robustness: dict[str, Any] | None,
) -> str:
    hgb_val = val_pr_auc.get("hgb")
    log_val = val_pr_auc.get("logistic")
    hgb_test = test_pr_auc.get("hgb")
    if hgb_val is not None and hgb_test is not None and hgb_val > 0 and hgb_test < 0.5 * hgb_val:
        return "NO_MODEL_READY"
    if robustness:
        values = [item["hgb_pr_auc"] for item in robustness.get("retrain", []) if item.get("hgb_pr_auc") is not None]
        if values and statistics.mean(values) < 0.15:
            return "NO_MODEL_READY"
    if served_predictor == "hgb" and ml_promoted:
        relative = relative_pr_auc_improvement(log_val, hgb_val)
        if relative is None or relative < MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT:
            return "LOGISTIC_PROMOTED"
        return "HGB_PROMOTED"
    if served_predictor == "logistic" and ml_promoted:
        return "LOGISTIC_PROMOTED"
    if served_predictor in {"prevalence", "oem_threshold"}:
        return "BASELINE_RETAINED"
    return "NO_MODEL_READY"


def evaluate_all_predictors(
    artifact: FailureRiskArtifact,
    rows: list[FeatureRow],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    threshold: float,
) -> dict[str, Any]:
    y_true = labels_of(rows)
    report: dict[str, Any] = {}
    for name in ("prevalence", "oem_threshold", "logistic", "hgb"):
        scores = _scores_for(name, artifact, rows, feature_names=feature_names)
        report[name] = {
            **classification_report(y_true, scores, threshold if name == artifact.served_predictor else 0.5),
            "operational": operational_metrics(
                rows,
                apply_threshold(scores, threshold if name == artifact.served_predictor else 0.5),
            ),
        }
        if name in {"logistic", "hgb"}:
            report[name]["calibration"] = calibration_summary(y_true, scores)
    return report


def run_validation_experiment(
    rows: list[FeatureRow],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    hgb_param_grid: tuple[dict[str, Any], ...] = (HGB_DEFAULT_PARAMS,),
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[FailureRiskArtifact, dict[str, Any]]:
    return train_from_rows(
        rows,
        include_test=False,
        hgb_param_grid=hgb_param_grid,
        feature_names=feature_names,
        extra_metadata=extra_metadata,
    )


def score_held_out_test(
    artifact: FailureRiskArtifact,
    rows: list[FeatureRow],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> dict[str, Any]:
    test = [row for row in rows if row.split == "test"]
    if not test:
        return {}
    return evaluate_all_predictors(
        artifact, test, feature_names=feature_names, threshold=artifact.threshold
    )


def save_versioned_artifact(
    artifact: FailureRiskArtifact,
    *,
    digest: str,
    artifacts_root: Path,
    promote_canonical: bool,
) -> dict[str, str]:
    experiment_dir = artifacts_root / "experiments" / digest[:12]
    experiment_path = persist_artifact(artifact, experiment_dir)
    paths = {
        "experiment_joblib": str(experiment_path),
        "experiment_metadata": str(experiment_dir / f"{MODEL_VERSION}.metadata.json"),
    }
    if promote_canonical:
        canonical = persist_artifact(artifact, artifacts_root)
        paths["canonical_joblib"] = str(canonical)
        paths["canonical_metadata"] = str(artifacts_root / f"{MODEL_VERSION}.metadata.json")
    return paths
