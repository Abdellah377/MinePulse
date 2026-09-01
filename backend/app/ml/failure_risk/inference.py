"""Failure-risk inference. HTTP is via equipment detail, not a dedicated ML route.

Never returns a 0% risk score when the prediction is unavailable.
The served predictor is whatever the loaded artifact records; runtime never
promotes HGB (or anything else) from a live score.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ml.failure_risk.contracts import (
    DATA_CLASS,
    MODEL_VERSION,
    TRAINING_DATA_TYPE,
    FailureRiskPrediction,
    FailureRiskStatus,
    RiskLevel,
)
from app.ml.failure_risk.dataset import FailureRiskSnapshot, load_snapshot, mechanical_incidents, telemetry_span
from app.ml.failure_risk.features import FEATURE_NAMES, FEATURE_VERSION, build_feature_rows
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

logger = logging.getLogger(__name__)

METADATA_SIDECAR = f"{MODEL_VERSION}.metadata.json"
_LEARNED_PREDICTORS = frozenset({"logistic", "hgb"})
_BASELINE_PREDICTORS = frozenset({"prevalence", "oem_threshold"})
_ALLOWED_PREDICTORS = _LEARNED_PREDICTORS | _BASELINE_PREDICTORS

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
    """Map probability onto display bands using the served classification threshold.

    HIGH means the served classifier would fire (p >= artifact threshold;
    Failure-Risk V1 logistic ≈ 0.949). MEDIUM is the lower half of that scale.
    These bands are not a second operating threshold.
    """

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


def _incompatible(loaded: object, detail: str) -> FailureRiskPrediction:
    return _unavailable(
        detail=detail,
        model_version=getattr(loaded, "model_version", None) or MODEL_VERSION,
        model_status=getattr(loaded, "model_status", None),
        served_predictor=getattr(loaded, "served_predictor", None),
        threshold=getattr(loaded, "threshold", None),
    )


def _sidecar_metadata(joblib_path: Path) -> dict | None:
    sidecar = joblib_path.with_name(METADATA_SIDECAR)
    if not sidecar.is_file():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def validate_served_artifact(
    loaded: FailureRiskArtifact,
    *,
    require_metadata: bool = False,
    sidecar: dict | None = None,
) -> FailureRiskArtifact | FailureRiskPrediction:
    """Reject missing, corrupt, or unaligned artifacts. Never rewrite served_predictor."""

    if not isinstance(loaded, FailureRiskArtifact):
        return _unavailable(detail="Model artifact is unreadable.")
    if loaded.model_version and loaded.model_version != MODEL_VERSION:
        return _incompatible(loaded, "Model version is incompatible.")
    if tuple(loaded.feature_names) != FEATURE_NAMES:
        return _incompatible(loaded, "Feature schema mismatch.")
    name = loaded.served_predictor
    if name not in _ALLOWED_PREDICTORS:
        return _incompatible(loaded, "Served predictor is missing or unknown.")
    if name == "logistic" and loaded.logistic is None:
        return _incompatible(loaded, "Served logistic pipeline is missing.")
    if name == "hgb" and loaded.hgb is None:
        return _incompatible(loaded, "Served HGB pipeline is missing.")
    try:
        threshold = float(loaded.threshold)
    except (TypeError, ValueError):
        return _incompatible(loaded, "Artifact threshold is invalid.")
    if not 0.0 < threshold <= 1.0:
        return _incompatible(loaded, "Artifact threshold is invalid.")

    metadata = loaded.metadata if isinstance(loaded.metadata, dict) else {}
    if sidecar is not None:
        if not sidecar:
            return _incompatible(loaded, "Artifact metadata is unreadable.")
        metadata = {**metadata, **sidecar}
        served_sidecar = sidecar.get("served_predictor")
        if served_sidecar is not None and served_sidecar != name:
            return _incompatible(loaded, "Sidecar served predictor does not match the artifact.")
    if require_metadata and not metadata:
        return _incompatible(loaded, "Artifact metadata is missing.")
    if metadata:
        training_type = metadata.get("training_data_type")
        if require_metadata and training_type != TRAINING_DATA_TYPE:
            return _incompatible(loaded, "Training-data type is incompatible.")
        if training_type not in (None, TRAINING_DATA_TYPE):
            return _incompatible(loaded, "Training-data type is incompatible.")
        meta_version = metadata.get("model_version")
        if meta_version not in (None, MODEL_VERSION):
            return _incompatible(loaded, "Model version is incompatible.")
        served_meta = metadata.get("served_predictor")
        if served_meta is not None and served_meta != name:
            return _incompatible(loaded, "Served predictor metadata does not match the artifact.")
        feature_version = metadata.get("feature_version")
        if feature_version is not None and feature_version != FEATURE_VERSION:
            return _incompatible(loaded, "Feature version is incompatible.")
        schema = metadata.get("feature_schema") or metadata.get("feature_set")
        if schema is not None and tuple(schema) != FEATURE_NAMES:
            return _incompatible(loaded, "Feature schema mismatch.")
    return loaded


def resolve_artifact(
    *,
    artifacts_dir: Path | None = None,
    artifact: FailureRiskArtifact | None = None,
) -> FailureRiskArtifact | FailureRiskPrediction:
    if artifact is not None:
        return validate_served_artifact(artifact, require_metadata=False)
    path = (artifacts_dir or DEFAULT_ARTIFACT_DIR) / ARTIFACT_FILE
    try:
        loaded = load_artifact(path)
    except FileNotFoundError:
        return _unavailable(detail="Model artifact is missing.")
    except Exception:
        logger.exception("Failure-Risk artifact could not be loaded")
        return _unavailable(detail="Model artifact is unreadable.")
    return validate_served_artifact(loaded, require_metadata=True, sidecar=_sidecar_metadata(path))


def _scores(artifact: FailureRiskArtifact, rows) -> list[float]:
    name = artifact.served_predictor
    if name == "logistic":
        if artifact.logistic is None:
            raise ValueError("Served logistic pipeline is missing.")
        return predict_proba_positive(artifact.logistic, rows)
    if name == "hgb":
        if artifact.hgb is None:
            raise ValueError("Served HGB pipeline is missing.")
        return predict_proba_positive(artifact.hgb, rows)
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
    try:
        probability = _scores(artifact, rows)[0]
    except Exception:
        logger.exception("Failure-Risk served predictor could not score a window")
        return _unavailable(
            equipment_id=equipment_id,
            equipment_code=info.code,
            prediction_timestamp=t,
            feature_timestamp=latest_telemetry,
            detail="Served predictor could not score this window.",
            model_version=artifact.model_version,
            model_status=artifact.model_status,
            served_predictor=artifact.served_predictor,
        )
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
