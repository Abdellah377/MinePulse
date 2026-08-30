"""Train Failure-Risk V1: incident-grouped split, baselines, LR, HGB, artifact.

PROTOTYPE / SYNTHETIC-DATA MODEL. Not field-validated.

Usage (from backend/):

    python -m app.ml.failure_risk.train
    python -m app.ml.failure_risk.train --eval-only
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sklearn

from app.ml.failure_risk.baselines import FailureRiskBaselines
from app.ml.failure_risk.contracts import (
    MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT,
    MODEL_VERSION,
    SYNTHETIC_DATA_WARNING,
    TRAINING_DATA_TYPE,
)
from app.ml.failure_risk.dataset import build_window_split, load_snapshot, snapshot_summary
from app.ml.failure_risk.evaluation import (
    apply_threshold,
    classification_report,
    labels_of,
    operational_metrics,
    ranking_metrics,
    select_threshold_max_f1,
)
from app.ml.failure_risk.features import FEATURE_NAMES, FeatureRow, build_feature_rows, missing_rates
from app.ml.failure_risk.model import (
    ARTIFACT_FILE,
    DEFAULT_ARTIFACT_DIR,
    HGB_GRID,
    FailureRiskArtifact,
    build_hgb_pipeline,
    build_logistic_pipeline,
    feature_importance,
    predict_proba_positive,
    rows_to_matrix,
    save_artifact as write_joblib,
)
from app.ml.failure_risk.policy import select_served_predictor
from app.ml.failure_risk.spec import (
    HISTORY_LOOKBACK_MINUTES,
    HORIZON_MINUTES,
    MIN_LEAD_TIME_MINUTES,
    STRIDE_MINUTES,
    split_has_incident_leakage,
)

METADATA_NAME = f"{MODEL_VERSION}.metadata.json"


def _split_rows(rows: list[FeatureRow]) -> tuple[list[FeatureRow], list[FeatureRow], list[FeatureRow]]:
    train = [row for row in rows if row.split == "train"]
    val = [row for row in rows if row.split == "validation"]
    test = [row for row in rows if row.split == "test"]
    return train, val, test


def _split_bounds(rows: list[FeatureRow]) -> dict[str, Any]:
    if not rows:
        return {"first_prediction_time": None, "last_prediction_time": None, "n": 0, "n_positive": 0}
    ordered = sorted(rows, key=lambda row: row.prediction_time)
    return {
        "first_prediction_time": ordered[0].prediction_time.isoformat(),
        "last_prediction_time": ordered[-1].prediction_time.isoformat(),
        "n": len(rows),
        "n_positive": sum(1 for row in rows if row.label == 1),
        "n_negative": sum(1 for row in rows if row.label == 0),
    }


def _fit_hgb(train: list[FeatureRow], val: list[FeatureRow]) -> tuple[Any, dict[str, float | None], dict[str, Any]]:
    y_train = labels_of(train)
    y_val = labels_of(val)
    best_pipeline = None
    best_metrics: dict[str, float | None] | None = None
    best_params: dict[str, Any] = {}
    for params in HGB_GRID:
        pipeline = build_hgb_pipeline(**params)
        pipeline.fit(rows_to_matrix(train), y_train)
        metrics = ranking_metrics(y_val, predict_proba_positive(pipeline, val))
        if best_metrics is None or (metrics["pr_auc"] or -1) > (best_metrics["pr_auc"] or -1):
            best_pipeline = pipeline
            best_metrics = metrics
            best_params = params
    assert best_pipeline is not None and best_metrics is not None
    return best_pipeline, best_metrics, best_params


def _scores_for(name: str, artifact: FailureRiskArtifact, rows: list[FeatureRow]) -> list[float]:
    if name == "logistic":
        if artifact.logistic is None:
            raise ValueError("Logistic pipeline missing.")
        return predict_proba_positive(artifact.logistic, rows)
    if name == "hgb":
        if artifact.hgb is None:
            raise ValueError("HGB pipeline missing.")
        return predict_proba_positive(artifact.hgb, rows)
    return artifact.baselines.predict(name, rows)


def _importance_for(name: str, artifact: FailureRiskArtifact) -> list[tuple[str, float]]:
    if name == "logistic" and artifact.logistic is not None:
        return feature_importance(artifact.logistic, "logistic")[:12]
    if name == "hgb" and artifact.hgb is not None:
        return feature_importance(artifact.hgb, "hgb")[:12]
    return []


def train_from_rows(
    rows: list[FeatureRow],
    *,
    excluded: dict[str, int] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[FailureRiskArtifact, dict[str, Any]]:
    train, val, test = _split_rows(rows)
    if not train or not val:
        raise ValueError("Need non-empty train and validation splits.")

    baselines = FailureRiskBaselines().fit(train)
    y_val = labels_of(val)
    baseline_val = {
        "prevalence": ranking_metrics(y_val, baselines.predict_prevalence(val)),
        "oem_threshold": ranking_metrics(y_val, baselines.predict_oem_score(val)),
    }
    logistic = build_logistic_pipeline()
    logistic.fit(rows_to_matrix(train), labels_of(train))
    logistic_val = ranking_metrics(y_val, predict_proba_positive(logistic, val))
    hgb, hgb_val, hgb_params = _fit_hgb(train, val)

    decision = select_served_predictor(
        logistic_pr_auc=logistic_val["pr_auc"],
        hgb_pr_auc=hgb_val["pr_auc"],
        baseline_pr_auc={name: metrics["pr_auc"] for name, metrics in baseline_val.items()},
        threshold=MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT,
    )

    artifact = FailureRiskArtifact(
        logistic=logistic,
        hgb=hgb,
        baselines=baselines,
        served_predictor=decision.served_predictor,
        threshold=0.5,
        feature_names=FEATURE_NAMES,
        model_status=decision.model_status,
    )
    val_scores = _scores_for(decision.served_predictor, artifact, val)
    threshold, val_operating = select_threshold_max_f1(y_val, val_scores)
    artifact.threshold = threshold
    importance = _importance_for(decision.served_predictor, artifact)
    artifact.top_signals = tuple(name for name, _ in importance[:5])

    y_test = labels_of(test) if test else []
    test_scores = _scores_for(decision.served_predictor, artifact, test) if test else []
    served_val = classification_report(y_val, val_scores, threshold)
    served_test = classification_report(y_test, test_scores, threshold) if test else {}
    baseline_test = (
        {
            "prevalence": ranking_metrics(y_test, baselines.predict_prevalence(test)),
            "oem_threshold": ranking_metrics(y_test, baselines.predict_oem_score(test)),
        }
        if test
        else {}
    )
    logistic_test = ranking_metrics(y_test, predict_proba_positive(logistic, test)) if test else {}
    hgb_test = ranking_metrics(y_test, predict_proba_positive(hgb, test)) if test else {}

    report: dict[str, Any] = {
        "model_name": "failure_risk",
        "model_version": MODEL_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_data_type": TRAINING_DATA_TYPE,
        "synthetic_data_warning": SYNTHETIC_DATA_WARNING,
        "target": "STOPPED_MECHANICAL incident starts in (T, T+60min] with 15-minute lead time",
        "prediction_timestamp_definition": "equipment prediction time T",
        "horizon_minutes": HORIZON_MINUTES,
        "minimum_lead_time_min": MIN_LEAD_TIME_MINUTES,
        "history_lookback_min": HISTORY_LOOKBACK_MINUTES,
        "sampling_stride_min": STRIDE_MINUTES,
        "class_imbalance_handling": "class_weight=balanced; no oversampling",
        "threshold_selection": "maximize F1 on validation scores only",
        "selected_threshold": threshold,
        "feature_schema": list(FEATURE_NAMES),
        "sklearn_version": sklearn.__version__,
        "dataset_sample_count": len(rows),
        "excluded_sample_count": excluded or {},
        "missing_rates_pct": missing_rates(rows),
        "split": {
            "strategy": "chronological_incident_grouped_70_15_15_no_shuffle",
            "train": _split_bounds(train),
            "validation": _split_bounds(val),
            "test": _split_bounds(test),
        },
        "hgb_params": hgb_params,
        "baseline_validation": baseline_val,
        "baseline_test": baseline_test,
        "logistic_validation": logistic_val,
        "logistic_test": logistic_test,
        "hgb_validation": hgb_val,
        "hgb_test": hgb_test,
        "served_predictor": decision.served_predictor,
        "served_validation": served_val,
        "served_test": served_test,
        "served_validation_operating": val_operating,
        "served_validation_operational": operational_metrics(val, apply_threshold(val_scores, threshold)),
        "served_test_operational": operational_metrics(test, apply_threshold(test_scores, threshold)) if test else {},
        "feature_importance": [{"feature": name, "weight": weight} for name, weight in importance],
        "model_status": decision.model_status.value,
        "selection": {
            "uses": "validation_only",
            "test_set_used_for_selection": False,
            "test_set_used_for_threshold": False,
        },
    }
    report.update(decision.metadata())
    if extra_metadata:
        report.update(extra_metadata)
    artifact.metadata = report
    return artifact, report


def persist_artifact(artifact: FailureRiskArtifact, artifacts_dir: Path) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = write_joblib(artifact, artifacts_dir / ARTIFACT_FILE)
    (artifacts_dir / METADATA_NAME).write_text(json.dumps(artifact.metadata, indent=2, default=str), encoding="utf-8")
    return path


def train_from_database(session, artifacts_dir: Path) -> dict[str, Any]:
    snapshot = load_snapshot(session)
    split, exclusions, _incidents = build_window_split(snapshot)
    if split_has_incident_leakage(split):
        raise ValueError("Incident leakage across temporal splits.")
    windows = list(split.train) + list(split.validation) + list(split.test)
    rows = build_feature_rows(windows, snapshot)
    extra = snapshot_summary(snapshot, split, exclusions)
    extra["n_incidents"] = len({window.incident_id for window in windows if window.incident_id})
    artifact, report = train_from_rows(rows, excluded=exclusions, extra_metadata=extra)
    persist_artifact(artifact, artifacts_dir)
    return report


def _print_report(report: dict[str, Any]) -> None:
    print("PROTOTYPE / SYNTHETIC-DATA MODEL — not field-validated")
    print(f"version={report['model_version']}  status={report['model_status']}")
    print(f"rows={report['dataset_sample_count']}  excluded={report['excluded_sample_count']}")
    print(
        "split train/val/test = "
        f"{report['split']['train']['n']}/{report['split']['validation']['n']}/{report['split']['test']['n']}"
    )
    print(f"best baseline={report['best_baseline']}  val PR-AUC={report['best_baseline_validation_pr_auc']}")
    print(f"logistic val PR-AUC={report['logistic_validation']['pr_auc']}  hgb val PR-AUC={report['hgb_validation']['pr_auc']}")
    print(f"served={report['served_predictor']}  threshold={report['selected_threshold']}  ml_promoted={report['ml_promoted']}")
    print(f"reason={report['decision_reason']}")
    print(f"served val={report['served_validation']}")
    print(f"served test={report['served_test']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train failure-risk V1 (synthetic prototype).")
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--eval-only", action="store_true", help="Print saved metadata without retraining.")
    args = parser.parse_args(argv)
    if args.eval_only:
        meta_path = args.artifacts_dir / METADATA_NAME
        print(meta_path.read_text(encoding="utf-8"))
        return 0
    from app.db.database import SessionLocal

    with SessionLocal() as session:
        report = train_from_database(session, args.artifacts_dir)
    _print_report(report)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
