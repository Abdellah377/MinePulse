"""Failure-risk V1 prototype. Trained only on synthetic MinePulse data."""

from app.ml.failure_risk.contracts import (
    FailureRiskPrediction,
    FailureRiskStatus,
    MODEL_VERSION,
    ModelStatus,
    RiskLevel,
)
from app.ml.failure_risk.spec import HORIZON_MINUTES, MIN_LEAD_TIME_MINUTES

__all__ = [
    "FailureRiskPrediction",
    "FailureRiskStatus",
    "HORIZON_MINUTES",
    "MIN_LEAD_TIME_MINUTES",
    "MODEL_VERSION",
    "ModelStatus",
    "RiskLevel",
]
