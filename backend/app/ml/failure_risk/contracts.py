"""Typed contracts for failure-risk prediction V1.

PROTOTYPE / SYNTHETIC-DATA MODEL — not field-validated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import EquipmentType
from app.ml.failure_risk.spec import MODEL_VERSION as SPEC_MODEL_VERSION

MODEL_VERSION = SPEC_MODEL_VERSION
TRAINING_DATA_TYPE = "synthetic"
DATA_CLASS = "synthetic_prototype"
PREDICTION_TIMESTAMP_DEFINITION = "equipment prediction time T"
MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT = 0.05
SYNTHETIC_DATA_WARNING = (
    "This model is trained entirely on synthetic MinePulse simulator data "
    "and is intended for prototype validation only. It is not field-validated."
)
FAILURE_RISK_ELIGIBLE_TYPES = (EquipmentType.HAUL_TRUCK,)


class FailureRiskStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ModelStatus(str, Enum):
    MODEL_BEATS_BASELINE = "MODEL_BEATS_BASELINE"
    BASELINE_NOT_BEATEN = "BASELINE_NOT_BEATEN"


class FailureRiskPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    equipment_id: int | None = None
    equipment_code: str | None = None
    prediction_timestamp: datetime | None = None
    horizon_minutes: int = 60
    risk_probability: float | None = None
    risk_level: RiskLevel | None = None
    model_version: str = MODEL_VERSION
    model_type: str | None = None
    threshold: float | None = None
    feature_timestamp: datetime | None = None
    status: FailureRiskStatus
    data_class: str = DATA_CLASS
    served_predictor: str | None = None
    model_status: ModelStatus | None = None
    top_predictive_signals: list[str] | None = None
    detail: str | None = Field(default=None, description="Why the result is unavailable, if applicable.")
