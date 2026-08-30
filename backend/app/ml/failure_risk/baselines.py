"""Deterministic Failure-Risk V1 baselines.

Uses repository OEM/simulation thresholds. Does not invent new limits.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ml.failure_risk.features import FeatureRow
from app.oem.thresholds import classify_value

OEM_SCORE_SENSORS = (
    "engine_temp_c",
    "coolant_temp_c",
    "oil_pressure_kpa",
    "battery_voltage",
)


def oem_warn_count(row: FeatureRow) -> float:
    count = 0.0
    for name in OEM_SCORE_SENSORS:
        value = row.values.get(f"{name}_latest")
        if value is None:
            continue
        if classify_value(name, float(value)) in {"warning", "critical"}:
            count += 1.0
    return count


@dataclass
class FailureRiskBaselines:
    prevalence: float = 0.0

    def fit(self, rows: list[FeatureRow]) -> "FailureRiskBaselines":
        labels = [row.label for row in rows if row.label is not None]
        if not labels:
            raise ValueError("Cannot fit baselines: no training labels.")
        self.prevalence = sum(1 for label in labels if label == 1) / len(labels)
        return self

    def predict_prevalence(self, rows: list[FeatureRow]) -> list[float]:
        return [self.prevalence for _ in rows]

    def predict_oem_score(self, rows: list[FeatureRow]) -> list[float]:
        return [oem_warn_count(row) for row in rows]

    def predict_oem_binary(self, rows: list[FeatureRow]) -> list[int]:
        return [1 if score >= 1.0 else 0 for score in self.predict_oem_score(rows)]

    def predict(self, name: str, rows: list[FeatureRow]) -> list[float]:
        if name == "prevalence":
            return self.predict_prevalence(rows)
        if name == "oem_threshold":
            return self.predict_oem_score(rows)
        raise KeyError(name)
