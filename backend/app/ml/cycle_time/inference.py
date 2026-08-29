"""Internal cycle-time inference. No HTTP route in V1.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.ml.cycle_time.contracts import (
    DATA_CLASS,
    MODEL_VERSION,
    CycleTimePrediction,
    CycleTimeStatus,
)
from app.ml.cycle_time.dataset import CycleSnapshot, load_snapshot
from app.ml.cycle_time.evaluation import apply_residual_bounds
from app.ml.cycle_time.features import FEATURE_NAMES, build_feature_rows
from app.ml.cycle_time.model import ARTIFACT_FILE, DEFAULT_ARTIFACT_DIR, CycleTimeArtifact, load_artifact, predict_pipeline


def _served_predictions(artifact: CycleTimeArtifact, rows) -> list[float]:
    if artifact.served_predictor == "hgb":
        if artifact.pipeline is None:
            raise ValueError("HGB pipeline missing from artifact.")
        return predict_pipeline(artifact.pipeline, rows)
    return artifact.baselines.predict(artifact.served_predictor, rows)


def predict_feature_rows(artifact: CycleTimeArtifact, rows) -> list[tuple[float, float, float]]:
    preds = _served_predictions(artifact, rows)
    return [apply_residual_bounds(pred, artifact.residual_q10, artifact.residual_q90) for pred in preds]


def resolve_artifact(
    *,
    artifacts_dir: Path | None = None,
    artifact: CycleTimeArtifact | None = None,
) -> CycleTimeArtifact | CycleTimePrediction:
    if artifact is not None:
        loaded = artifact
    else:
        try:
            loaded = load_artifact((artifacts_dir or DEFAULT_ARTIFACT_DIR) / ARTIFACT_FILE)
        except FileNotFoundError:
            return CycleTimePrediction(status=CycleTimeStatus.UNAVAILABLE, detail="Model artifact is missing.")
    if tuple(loaded.feature_names) != FEATURE_NAMES:
        return CycleTimePrediction(
            status=CycleTimeStatus.UNAVAILABLE,
            detail="Feature schema mismatch.",
            model_version=loaded.model_version,
            model_status=loaded.model_status,
            served_predictor=loaded.served_predictor,
        )
    return loaded


def predict_from_snapshot(
    snapshot: CycleSnapshot,
    cycle_id: int,
    artifact: CycleTimeArtifact,
) -> CycleTimePrediction:
    cycle = next((row for row in snapshot.cycles if row.cycle_id == cycle_id), None)
    if cycle is None:
        return CycleTimePrediction(
            cycle_id=cycle_id,
            status=CycleTimeStatus.UNAVAILABLE,
            detail="Cycle not found.",
            model_version=artifact.model_version,
        )
    if cycle.started_at is None or cycle.truck_id is None:
        return CycleTimePrediction(
            cycle_id=cycle_id,
            equipment_id=cycle.truck_id,
            prediction_timestamp=cycle.started_at,
            feature_timestamp=cycle.started_at,
            status=CycleTimeStatus.INSUFFICIENT_HISTORY,
            detail="started_at and truck_id are required at prediction time.",
            model_version=artifact.model_version,
            model_status=artifact.model_status,
            served_predictor=artifact.served_predictor,
        )
    rows = build_feature_rows([cycle], snapshot, include_target=False)
    predicted, lower, upper = predict_feature_rows(artifact, rows)[0]
    return CycleTimePrediction(
        equipment_id=cycle.truck_id,
        cycle_id=cycle.cycle_id,
        prediction_timestamp=cycle.started_at,
        predicted_minutes=round(predicted, 2),
        lower_bound_minutes=round(lower, 2),
        upper_bound_minutes=round(upper, 2),
        model_version=artifact.model_version or MODEL_VERSION,
        feature_timestamp=cycle.started_at,
        status=CycleTimeStatus.AVAILABLE,
        data_class=DATA_CLASS,
        served_predictor=artifact.served_predictor,
        model_status=artifact.model_status,
    )


def predict_cycle_time(
    session: Session,
    cycle_id: int,
    *,
    artifacts_dir: Path | None = None,
    artifact: CycleTimeArtifact | None = None,
) -> CycleTimePrediction:
    resolved = resolve_artifact(artifacts_dir=artifacts_dir, artifact=artifact)
    if isinstance(resolved, CycleTimePrediction):
        return resolved.model_copy(update={"cycle_id": cycle_id})
    return predict_from_snapshot(load_snapshot(session), cycle_id, resolved)
