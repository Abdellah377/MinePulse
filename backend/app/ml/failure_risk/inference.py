"""Failure-risk inference. HTTP is via equipment detail, not a dedicated ML route.

Never returns a 0% risk score when the prediction is unavailable.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ml.failure_risk.contracts import (
    DATA_CLASS,
    MODEL_VERSION,
    FailureRiskPrediction,
    FailureRiskStatus,
    RiskLevel,
)
from app.ml.failure_risk.dataset import FailureRiskSnapshot, load_snapshot, mechanical_incidents, telemetry_span
from app.ml.failure_risk.features import FEATURE_NAMES, build_feature_rows
from app.ml.failure_risk.model import (
    ARTIFACT_FILE,
    DEFAULT_ARTIFACT_DIR,
    FailureRiskArtifact,
    load_artifact,
    predict_proba_positive,
)
from app.ml.failure_risk.spec import (
    HISTORY_LOOKBACK_MINUTES,
    HORIZON_MINUTES,
    MIN_HISTORY_MINUTES,
    LabeledWindow,
    classify_window,
)

# The batch simulator persists telemetry every two 60-second ticks by default
# (simulator.cli --sample-every-ticks=2). A complete cadence is accepted so a
# score at the boundary does not reject the latest normal sample.
MAX_TELEMETRY_AGE_SECONDS = 120


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def risk_level_for(probability: float, threshold: float) -> RiskLevel:
    if probability >= threshold:
        return RiskLevel.HIGH
    if probability >= 0.5 * threshold:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _unavailable(**kwargs) -> FailureRiskPrediction:
    payload = {
        "status": FailureRiskStatus.UNAVAILABLE,
        "risk_probability": None,
        "risk_level": None,
        "model_version": MODEL_VERSION,
        "data_class": DATA_CLASS,
        "horizon_minutes": HORIZON_MINUTES,
    }
    payload.update(kwargs)
    return FailureRiskPrediction(**payload)


def resolve_artifact(
    *,
    artifacts_dir: Path | None = None,
    artifact: FailureRiskArtifact | None = None,
) -> FailureRiskArtifact | FailureRiskPrediction:
    if artifact is not None:
        loaded = artifact
    else:
        try:
            loaded = load_artifact((artifacts_dir or DEFAULT_ARTIFACT_DIR) / ARTIFACT_FILE)
        except FileNotFoundError:
            return _unavailable(detail="Model artifact is missing.")
    if tuple(loaded.feature_names) != FEATURE_NAMES:
        return _unavailable(
            detail="Feature schema mismatch.",
            model_version=loaded.model_version,
            model_status=loaded.model_status,
            served_predictor=loaded.served_predictor,
        )
    return loaded


def _scores(artifact: FailureRiskArtifact, rows) -> list[float]:
    name = artifact.served_predictor
    if name in {"logistic", "hgb"}:
        pipeline = artifact.logistic if name == "logistic" else artifact.hgb
        if pipeline is None:
            raise ValueError(f"Served predictor {name} is missing from the artifact.")
        return predict_proba_positive(pipeline, rows)
    return artifact.baselines.predict(name, rows)


def _latest_telemetry_at_or_before(
    snapshot: FailureRiskSnapshot,
    equipment_id: int,
    prediction_time: datetime,
) -> datetime | None:
    observed = (
        _aware(sample.ts)
        for sample in snapshot.telemetry
        if sample.equipment_id == equipment_id and _aware(sample.ts) is not None and _aware(sample.ts) <= prediction_time
    )
    return max(observed, default=None)


def predict_from_snapshot(
    snapshot: FailureRiskSnapshot,
    equipment_id: int,
    prediction_time: datetime,
    artifact: FailureRiskArtifact,
) -> FailureRiskPrediction:
    t = _aware(prediction_time)
    info = snapshot.equipment.get(equipment_id)
    if info is None:
        return _unavailable(
            equipment_id=equipment_id,
            prediction_timestamp=t,
            detail="Equipment not found.",
            model_version=artifact.model_version,
        )
    latest_telemetry = _latest_telemetry_at_or_before(snapshot, equipment_id, t)
    if latest_telemetry is None:
        return _unavailable(
            equipment_id=equipment_id,
            equipment_code=info.code,
            prediction_timestamp=t,
            feature_timestamp=None,
            detail="No telemetry is available at or before the prediction time.",
            model_version=artifact.model_version,
            model_status=artifact.model_status,
            served_predictor=artifact.served_predictor,
        )
    lookback_start = t - timedelta(minutes=HISTORY_LOOKBACK_MINUTES)
    if latest_telemetry < lookback_start:
        return _unavailable(
            equipment_id=equipment_id,
            equipment_code=info.code,
            prediction_timestamp=t,
            feature_timestamp=latest_telemetry,
            detail="No telemetry sample exists in the 60-minute feature lookback.",
            model_version=artifact.model_version,
            model_status=artifact.model_status,
            served_predictor=artifact.served_predictor,
        )
    if (t - latest_telemetry).total_seconds() > MAX_TELEMETRY_AGE_SECONDS:
        return _unavailable(
            equipment_id=equipment_id,
            equipment_code=info.code,
            prediction_timestamp=t,
            feature_timestamp=latest_telemetry,
            detail="Latest telemetry is older than the 120-second sampling cadence.",
            model_version=artifact.model_version,
            model_status=artifact.model_status,
            served_predictor=artifact.served_predictor,
        )
    _start, _end, first_ts = telemetry_span(snapshot)
    incidents = mechanical_incidents(snapshot)
    window = classify_window(
        equipment_id=equipment_id,
        prediction_time=t,
        incidents=incidents,
        first_telemetry_ts=first_ts.get(equipment_id),
        min_history_minutes=MIN_HISTORY_MINUTES,
        min_lead_time_minutes=0,
        horizon_minutes=HORIZON_MINUTES,
    )
    if window.exclude_reason == "insufficient_history":
        return FailureRiskPrediction(
            equipment_id=equipment_id,
            equipment_code=info.code,
            prediction_timestamp=t,
            feature_timestamp=latest_telemetry,
            horizon_minutes=HORIZON_MINUTES,
            status=FailureRiskStatus.INSUFFICIENT_HISTORY,
            risk_probability=None,
            risk_level=None,
            model_version=artifact.model_version,
            model_status=artifact.model_status,
            served_predictor=artifact.served_predictor,
            detail="Fewer than 15 minutes of telemetry are available at T.",
        )
    if window.exclude_reason == "active_incident":
        return _unavailable(
            equipment_id=equipment_id,
            equipment_code=info.code,
            prediction_timestamp=t,
            feature_timestamp=latest_telemetry,
            detail="Equipment is in an active STOPPED_MECHANICAL incident.",
            model_version=artifact.model_version,
            model_status=artifact.model_status,
            served_predictor=artifact.served_predictor,
        )
    labeled = LabeledWindow(
        equipment_id=equipment_id,
        prediction_time=t,
        label=0,
        exclude_reason=None,
        incident_id=None,
        minutes_to_incident=None,
    )
    rows = build_feature_rows([labeled], snapshot)
    probability = _scores(artifact, rows)[0]
    level = risk_level_for(probability, artifact.threshold)
    return FailureRiskPrediction(
        equipment_id=equipment_id,
        equipment_code=info.code,
        prediction_timestamp=t,
        feature_timestamp=latest_telemetry,
        horizon_minutes=HORIZON_MINUTES,
        risk_probability=round(float(probability), 4),
        risk_level=level,
        model_version=artifact.model_version or MODEL_VERSION,
        model_type=artifact.served_predictor,
        threshold=artifact.threshold,
        status=FailureRiskStatus.AVAILABLE,
        data_class=DATA_CLASS,
        served_predictor=artifact.served_predictor,
        model_status=artifact.model_status,
        top_predictive_signals=list(artifact.top_signals) or None,
    )


def predict_failure_risk(
    session: Session,
    equipment_id: int,
    prediction_time: datetime,
    *,
    site_id: int,
    artifacts_dir: Path | None = None,
    artifact: FailureRiskArtifact | None = None,
) -> FailureRiskPrediction:
    return score_equipment(
        session,
        [equipment_id],
        prediction_time,
        site_id=site_id,
        artifacts_dir=artifacts_dir,
        artifact=artifact,
    )[equipment_id]


def score_equipment(
    session: Session,
    equipment_ids: list[int],
    prediction_time: datetime,
    *,
    site_id: int,
    artifacts_dir: Path | None = None,
    artifact: FailureRiskArtifact | None = None,
) -> dict[int, FailureRiskPrediction]:
    """Score many equipment ids against one resolved artifact and one operational snapshot."""

    resolved = resolve_artifact(artifacts_dir=artifacts_dir, artifact=artifact)
    if isinstance(resolved, FailureRiskPrediction):
        return {
            equipment_id: resolved.model_copy(
                update={"equipment_id": equipment_id, "prediction_timestamp": prediction_time}
            )
            for equipment_id in equipment_ids
        }
    snapshot = load_snapshot(session, site_id=site_id)
    return {
        equipment_id: predict_from_snapshot(snapshot, equipment_id, prediction_time, resolved)
        for equipment_id in equipment_ids
    }
