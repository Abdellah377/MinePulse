"""Typed contracts for cycle-time prediction V1.

PROTOTYPE / SYNTHETIC-DATA MODEL — not field-validated.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


MODEL_VERSION = "cycle_time_v1"
TRAINING_DATA_TYPE = "synthetic"
DATA_CLASS = "synthetic_prototype"
PREDICTION_TIMESTAMP_DEFINITION = "Cycle.started_at"
# Official V1 served strategy when HGB is not promoted: truck → route → global.
DETERMINISTIC_SERVED_PREDICTOR = "truck_route_global"
MIN_ML_RELATIVE_MAE_IMPROVEMENT = 0.05


class CycleTimeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class ModelStatus(str, Enum):
    MODEL_BEATS_BASELINE = "MODEL_BEATS_BASELINE"
    BASELINE_NOT_BEATEN = "BASELINE_NOT_BEATEN"


class CycleTimePrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    equipment_id: int | None = None
    cycle_id: int | None = None
    prediction_timestamp: datetime | None = None
    predicted_minutes: float | None = None
    lower_bound_minutes: float | None = None
    upper_bound_minutes: float | None = None
    model_version: str = MODEL_VERSION
    feature_timestamp: datetime | None = None
    status: CycleTimeStatus
    data_class: str = DATA_CLASS
    served_predictor: str | None = None
    model_status: ModelStatus | None = None
    detail: str | None = Field(default=None, description="Why the result is unavailable, if applicable.")
