"""Regression metrics for cycle-time V1. MAPE is intentionally not used."""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from statistics import mean, median

from app.ml.cycle_time.features import FeatureRow


def regression_metrics(y_true: list[float], y_pred: list[float]) -> dict[str, float]:
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("y_true and y_pred must be non-empty and aligned.")
    errors = [abs(actual - pred) for actual, pred in zip(y_true, y_pred)]
    squared = [(actual - pred) ** 2 for actual, pred in zip(y_true, y_pred)]
    return {
        "mae": round(mean(errors), 3),
        "median_ae": round(median(errors), 3),
        "rmse": round(sqrt(mean(squared)), 3),
        "pct_within_10_min": round(100.0 * mean(1.0 if err <= 10 else 0.0 for err in errors), 1),
        "pct_within_20_min": round(100.0 * mean(1.0 if err <= 20 else 0.0 for err in errors), 1),
        "n": float(len(y_true)),
    }


def residual_quantiles(y_true: list[float], y_pred: list[float], low: float = 0.10, high: float = 0.90) -> tuple[float, float]:
    residuals = sorted(actual - pred for actual, pred in zip(y_true, y_pred))
    if not residuals:
        return 0.0, 0.0

    def at(p: float) -> float:
        idx = min(len(residuals) - 1, max(0, int(round(p * (len(residuals) - 1)))))
        return float(residuals[idx])

    return at(low), at(high)


def apply_residual_bounds(prediction: float, q10: float, q90: float) -> tuple[float, float, float]:
    lower = prediction + q10
    upper = prediction + q90
    lower, upper = min(lower, upper), max(lower, upper)
    lower = min(lower, prediction)
    upper = max(upper, prediction)
    lower = max(0.0, lower)
    return prediction, lower, upper


def slice_metrics(rows: list[FeatureRow], y_pred: list[float], key: str, min_n: int = 8) -> dict[str, dict[str, float]]:
    grouped: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for row, pred in zip(rows, y_pred):
        if row.target_minutes is None:
            continue
        token = str(row.values.get(key) or "unknown")
        grouped[token][0].append(row.target_minutes)
        grouped[token][1].append(pred)
    return {name: regression_metrics(actuals, preds) for name, (actuals, preds) in grouped.items() if len(actuals) >= min_n}


def targets(rows: list[FeatureRow]) -> list[float]:
    out = [row.target_minutes for row in rows]
    if any(value is None for value in out):
        raise ValueError("Training/eval rows must have targets.")
    return [float(value) for value in out]


def improvement(baseline_mae: float, model_mae: float) -> dict[str, float | None]:
    absolute = round(baseline_mae - model_mae, 3)
    relative = round(absolute / baseline_mae, 4) if baseline_mae else None
    return {"absolute_mae": absolute, "relative_mae": relative}
