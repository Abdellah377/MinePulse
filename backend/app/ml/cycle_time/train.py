"""Train cycle-time V1: temporal split, baselines, HGB, versioned artifact.

PROTOTYPE / SYNTHETIC-DATA MODEL. Not field-validated.

Usage (from backend/):

    python -m app.ml.cycle_time.train
    python -m app.ml.cycle_time.train --eval-only
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sklearn

from app.ml.cycle_time.baselines import MedianBaselines
from app.ml.cycle_time.contracts import MODEL_VERSION, TRAINING_DATA_TYPE, ModelStatus
from app.ml.cycle_time.dataset import load_snapshot, select_training_cycles
from app.ml.cycle_time.evaluation import improvement, regression_metrics, residual_quantiles, slice_metrics, targets
from app.ml.cycle_time.features import FEATURE_NAMES, FeatureRow, build_feature_rows, missing_rates
from app.ml.cycle_time.model import (
    ARTIFACT_FILE,
    DEFAULT_ARTIFACT_DIR,
    GRID,
    CycleTimeArtifact,
    build_pipeline,
    predict_pipeline,
    rows_to_matrix,
    save_artifact as write_joblib,
)

METADATA_NAME = f"{MODEL_VERSION}.metadata.json"


def temporal_split(
    rows: list[FeatureRow],
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> tuple[list[FeatureRow], list[FeatureRow], list[FeatureRow]]:
    ordered = sorted(rows, key=lambda row: (row.started_at, row.cycle_id))
    n = len(ordered)
    if n == 0:
        return [], [], []
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))
    if n >= 3:
        train_end = min(max(1, train_end), n - 2)
        val_end = min(max(train_end + 1, val_end), n - 1)
    return ordered[:train_end], ordered[train_end:val_end], ordered[val_end:]


def _split_bounds(rows: list[FeatureRow]) -> dict[str, str | None]:
    if not rows:
        return {"first_started_at": None, "last_started_at": None, "n": 0}
    return {
        "first_started_at": rows[0].started_at.isoformat() if rows[0].started_at else None,
        "last_started_at": rows[-1].started_at.isoformat() if rows[-1].started_at else None,
        "n": len(rows),
    }


def _assert_temporal_order(train: list[FeatureRow], val: list[FeatureRow], test: list[FeatureRow]) -> None:
    parts = [train, val, test]
    ids: set[int] = set()
    last = None
    for part in parts:
        for row in part:
            if row.cycle_id in ids:
                raise ValueError("Split overlap: cycle appears in more than one partition.")
            ids.add(row.cycle_id)
            if last is not None and row.started_at is not None and last > row.started_at:
                raise ValueError("Splits are not temporally ordered.")
            if row.started_at is not None:
                last = row.started_at


def _select_hgb(train: list[FeatureRow], val: list[FeatureRow]) -> tuple[Any, dict[str, float], dict[str, Any]]:
    y_val = targets(val)
    best_pipeline = None
    best_metrics = None
    best_params: dict[str, Any] = {}
    for params in GRID:
        pipeline = build_pipeline(**params)
        pipeline.fit(rows_to_matrix(train), targets(train))
        metrics = regression_metrics(y_val, predict_pipeline(pipeline, val))
        if best_metrics is None or metrics["mae"] < best_metrics["mae"]:
            best_pipeline = pipeline
            best_metrics = metrics
            best_params = params
    assert best_pipeline is not None and best_metrics is not None
    return best_pipeline, best_metrics, best_params


def _predict_served(artifact: CycleTimeArtifact, rows: list[FeatureRow]) -> list[float]:
    if artifact.served_predictor == "hgb":
        if artifact.pipeline is None:
            raise ValueError("Served predictor is hgb but pipeline is missing.")
        return predict_pipeline(artifact.pipeline, rows)
    return artifact.baselines.predict(artifact.served_predictor, rows)


def train_from_rows(
    rows: list[FeatureRow],
    *,
    excluded: dict[str, int] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[CycleTimeArtifact, dict[str, Any]]:
    train, val, test = temporal_split(rows)
    _assert_temporal_order(train, val, test)
    if not train or not val:
        raise ValueError("Need non-empty train and validation splits.")

    baselines = MedianBaselines().fit(train)
    baseline_val = {
        "global": regression_metrics(targets(val), baselines.predict_global(val)),
        "route": regression_metrics(targets(val), baselines.predict_route(val)),
        "truck": regression_metrics(targets(val), baselines.predict_truck(val)),
    }
    baseline_test = {
        "global": regression_metrics(targets(test), baselines.predict_global(test)) if test else {},
        "route": regression_metrics(targets(test), baselines.predict_route(test)) if test else {},
        "truck": regression_metrics(targets(test), baselines.predict_truck(test)) if test else {},
    }
    hgb, hgb_val, hgb_params = _select_hgb(train, val)
    hgb_test = regression_metrics(targets(test), predict_pipeline(hgb, test)) if test else {}

    baseline_maes = {name: metrics["mae"] for name, metrics in baseline_val.items()}
    best_baseline_name = min(baseline_maes, key=baseline_maes.get)
    best_baseline_mae = baseline_maes[best_baseline_name]
    if hgb_val["mae"] < best_baseline_mae:
        served = "hgb"
        status = ModelStatus.MODEL_BEATS_BASELINE
    else:
        served = best_baseline_name
        status = ModelStatus.BASELINE_NOT_BEATEN

    artifact = CycleTimeArtifact(
        pipeline=hgb,
        baselines=baselines,
        served_predictor=served,
        residual_q10=0.0,
        residual_q90=0.0,
        feature_names=FEATURE_NAMES,
        model_status=status,
    )
    val_pred = _predict_served(artifact, val)
    q10, q90 = residual_quantiles(targets(val), val_pred)
    artifact.residual_q10 = q10
    artifact.residual_q90 = q90
    served_val = regression_metrics(targets(val), val_pred)
    served_test = regression_metrics(targets(test), _predict_served(artifact, test)) if test else {}

    report: dict[str, Any] = {
        "model_name": "cycle_time",
        "model_version": MODEL_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_data_type": TRAINING_DATA_TYPE,
        "synthetic_data_warning": (
            "This model is trained entirely on synthetic MinePulse simulator data "
            "and is intended for prototype validation only. It is not field-validated."
        ),
        "target": "Cycle.total_duration_sec / 60",
        "prediction_timestamp_definition": "Cycle.started_at",
        "feature_schema": list(FEATURE_NAMES),
        "sklearn_version": sklearn.__version__,
        "dataset_sample_count": len(rows),
        "excluded_sample_count": excluded or {},
        "missing_rates_pct": missing_rates(rows),
        "split": {
            "strategy": "temporal_started_at_70_15_15_no_shuffle",
            "train": _split_bounds(train),
            "validation": _split_bounds(val),
            "test": _split_bounds(test),
        },
        "hgb_params": hgb_params,
        "baseline_validation": baseline_val,
        "baseline_test": baseline_test,
        "hgb_validation": hgb_val,
        "hgb_test": hgb_test,
        "served_predictor": served,
        "served_validation": served_val,
        "served_test": served_test,
        "best_baseline": best_baseline_name,
        "best_baseline_validation": baseline_val[best_baseline_name],
        "ml_vs_best_baseline_validation": improvement(best_baseline_mae, hgb_val["mae"]),
        "uncertainty": {
            "method": "validation residual quantiles (10th-90th percentile) of the served predictor",
            "residual_q10": q10,
            "residual_q90": q90,
            "label": "empirical prototype interval; not a calibrated production probability",
        },
        "model_status": status.value,
        "slice_validation_by_route_origin": slice_metrics(val, val_pred, "origin_code"),
        "slice_validation_by_loader": slice_metrics(val, val_pred, "loader_code"),
    }
    if extra_metadata:
        report.update(extra_metadata)
    artifact.metadata = report
    return artifact, report


def persist_artifact(artifact: CycleTimeArtifact, artifacts_dir: Path) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = write_joblib(artifact, artifacts_dir / ARTIFACT_FILE)
    (artifacts_dir / METADATA_NAME).write_text(json.dumps(artifact.metadata, indent=2, default=str), encoding="utf-8")
    return path


def train_from_database(session, artifacts_dir: Path) -> dict[str, Any]:
    snapshot = load_snapshot(session)
    kept, excluded = select_training_cycles(snapshot.cycles)
    rows = build_feature_rows(kept, snapshot, include_target=True)
    artifact, report = train_from_rows(rows, excluded=excluded)
    persist_artifact(artifact, artifacts_dir)
    return report


def _print_report(report: dict[str, Any]) -> None:
    print("PROTOTYPE / SYNTHETIC-DATA MODEL — not field-validated")
    print(f"version={report['model_version']}  status={report['model_status']}")
    print(f"rows={report['dataset_sample_count']}  excluded={report['excluded_sample_count']}")
    print(f"split train/val/test = {report['split']['train']['n']}/{report['split']['validation']['n']}/{report['split']['test']['n']}")
    print(f"best baseline={report['best_baseline']}  val MAE={report['best_baseline_validation']['mae']}")
    print(f"HGB val MAE={report['hgb_validation']['mae']}  served={report['served_predictor']}")
    print(f"served val={report['served_validation']}")
    print(f"served test={report['served_test']}")
    print(f"uncertainty q10/q90={report['uncertainty']['residual_q10']}/{report['uncertainty']['residual_q90']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train cycle-time V1 (synthetic prototype).")
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
