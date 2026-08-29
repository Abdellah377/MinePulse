"""Haul-truck cycle-time prediction V1.

PROTOTYPE / SYNTHETIC-DATA MODEL. Trained only on MinePulse simulator cycles.
Not field-validated. Not production-validated.
"""

from app.ml.cycle_time.contracts import (
    CycleTimePrediction,
    CycleTimeStatus,
    ModelStatus,
    MODEL_VERSION,
)

__all__ = [
    "CycleTimePrediction",
    "CycleTimeStatus",
    "MODEL_VERSION",
    "ModelStatus",
]
