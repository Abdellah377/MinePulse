"""Current Failure-Risk V1 score for equipment detail. Not alert history."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Equipment
from app.ml.failure_risk.contracts import (
    DATA_CLASS,
    FAILURE_RISK_ELIGIBLE_TYPES,
    MODEL_VERSION,
    FailureRiskPrediction,
    FailureRiskStatus,
)
from app.ml.failure_risk.inference import predict_failure_risk
from app.ml.failure_risk.spec import HORIZON_MINUTES

logger = logging.getLogger(__name__)

_UNSUPPORTED_DETAIL = "Failure-Risk V1 supports haul trucks only."


def current_failure_risk(
    session: Session,
    equipment: Equipment,
    prediction_time: datetime,
) -> FailureRiskPrediction:
    """Return the live inference result; never invent a probability."""

    if equipment.type not in FAILURE_RISK_ELIGIBLE_TYPES:
        return FailureRiskPrediction(
            equipment_id=equipment.equipment_id,
            equipment_code=equipment.code,
            prediction_timestamp=prediction_time,
            horizon_minutes=HORIZON_MINUTES,
            status=FailureRiskStatus.UNAVAILABLE,
            risk_probability=None,
            risk_level=None,
            model_version=MODEL_VERSION,
            data_class=DATA_CLASS,
            detail=_UNSUPPORTED_DETAIL,
        )
    try:
        return predict_failure_risk(session, equipment.equipment_id, prediction_time)
    except Exception:
        logger.exception(
            "Failure-Risk inference failed for equipment detail",
            extra={"equipment_id": equipment.equipment_id},
        )
        return FailureRiskPrediction(
            equipment_id=equipment.equipment_id,
            equipment_code=equipment.code,
            prediction_timestamp=prediction_time,
            horizon_minutes=HORIZON_MINUTES,
            status=FailureRiskStatus.UNAVAILABLE,
            risk_probability=None,
            risk_level=None,
            model_version=MODEL_VERSION,
            data_class=DATA_CLASS,
            detail="Prediction unavailable.",
        )


def failure_risk_to_dto(prediction: FailureRiskPrediction) -> dict:
    timestamp = prediction.prediction_timestamp
    return {
        "equipmentId": prediction.equipment_id,
        "equipmentCode": prediction.equipment_code,
        "predictionTimestamp": timestamp.isoformat() if timestamp is not None else None,
        "horizonMinutes": prediction.horizon_minutes,
        "riskProbability": prediction.risk_probability,
        "riskLevel": prediction.risk_level,
        "modelVersion": prediction.model_version,
        "modelType": prediction.model_type,
        "servedPredictor": prediction.served_predictor,
        "threshold": prediction.threshold,
        "status": prediction.status,
        "dataClass": prediction.data_class,
        "topPredictiveSignals": list(prediction.top_predictive_signals or []),
        "detail": prediction.detail,
    }
