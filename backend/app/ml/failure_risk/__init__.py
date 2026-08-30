"""Failure-risk V1 dataset specification. Does not train a model."""

from app.ml.failure_risk.spec import (
    HORIZON_MINUTES,
    MIN_LEAD_TIME_MINUTES,
    MODEL_VERSION,
    VERDICT_FIXES,
    VERDICT_NOT_READY,
    VERDICT_READY,
)

__all__ = [
    "HORIZON_MINUTES",
    "MIN_LEAD_TIME_MINUTES",
    "MODEL_VERSION",
    "VERDICT_FIXES",
    "VERDICT_NOT_READY",
    "VERDICT_READY",
]
