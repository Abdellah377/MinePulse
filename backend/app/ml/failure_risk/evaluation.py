"""Classification and operational metrics for Failure-Risk V1.

Accuracy is not the primary metric.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from statistics import median

from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.ml.failure_risk.features import FeatureRow
from app.ml.failure_risk.spec import STRIDE_MINUTES


def labels_of(rows: list[FeatureRow]) -> list[int]:
    out = [row.label for row in rows]
    if any(value is None for value in out):
        raise ValueError("Evaluation rows must have labels.")
    return [int(value) for value in out]


def _safe_auc(scorer, y_true: list[int], scores: list[float]) -> float | None:
    if len(set(y_true)) < 2:
        return None
    return round(float(scorer(y_true, scores)), 4)


def ranking_metrics(y_true: list[int], scores: list[float]) -> dict[str, float | None]:
    if len(y_true) != len(scores) or not y_true:
        raise ValueError("y_true and scores must be non-empty and aligned.")
    return {
        "pr_auc": _safe_auc(average_precision_score, y_true, scores),
        "roc_auc": _safe_auc(roc_auc_score, y_true, scores),
        "n": float(len(y_true)),
        "n_positive": float(sum(y_true)),
        "n_negative": float(len(y_true) - sum(y_true)),
    }


def operating_metrics(y_true: list[int], y_hat: list[int]) -> dict[str, float]:
    if len(y_true) != len(y_hat) or not y_true:
        raise ValueError("y_true and y_hat must be non-empty and aligned.")
    tn, fp, fn, tp = confusion_matrix(y_true, y_hat, labels=[0, 1]).ravel()
    return {
        "precision": round(float(precision_score(y_true, y_hat, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_hat, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_hat, zero_division=0)), 4),
        "true_positives": float(tp),
        "false_positives": float(fp),
        "false_negatives": float(fn),
        "true_negatives": float(tn),
        "n": float(len(y_true)),
    }


def apply_threshold(scores: list[float], threshold: float) -> list[int]:
    return [1 if score >= threshold else 0 for score in scores]


def select_threshold_max_f1(y_true: list[int], scores: list[float]) -> tuple[float, dict[str, float]]:
    candidates = sorted({0.0, 1.0, *scores})
    if len(set(y_true)) < 2:
        return 0.5, operating_metrics(y_true, apply_threshold(scores, 0.5))
    best_t = 0.5
    best_metrics = operating_metrics(y_true, apply_threshold(scores, best_t))
    for threshold in candidates:
        metrics = operating_metrics(y_true, apply_threshold(scores, threshold))
        if metrics["f1"] > best_metrics["f1"] or (
            metrics["f1"] == best_metrics["f1"] and threshold < best_t
        ):
            best_t = float(threshold)
            best_metrics = metrics
    return best_t, best_metrics


def operational_metrics(
    rows: list[FeatureRow],
    y_hat: list[int],
    *,
    stride_minutes: int = STRIDE_MINUTES,
) -> dict[str, float | None]:
    if len(rows) != len(y_hat):
        raise ValueError("rows and y_hat must be aligned.")
    incident_windows: dict[str, list[tuple[FeatureRow, int]]] = {}
    for row, pred in zip(rows, y_hat):
        if row.incident_id is None or row.label != 1:
            continue
        incident_windows.setdefault(row.incident_id, []).append((row, pred))
    detected = 0
    lead_times: list[float] = []
    for windows in incident_windows.values():
        hits = [item[0].minutes_to_incident for item in windows if item[1] == 1 and item[0].minutes_to_incident is not None]
        if hits:
            detected += 1
            lead_times.append(max(hits))
    n_incidents = len(incident_windows)
    fp = sum(1 for row, pred in zip(rows, y_hat) if row.label == 0 and pred == 1)
    hours = len(rows) * stride_minutes / 60.0
    return {
        "incidents_in_split": float(n_incidents),
        "incidents_detected": float(detected),
        "incident_recall": round(detected / n_incidents, 4) if n_incidents else None,
        "false_alarms_per_equipment_hour": round(fp / hours, 4) if hours else None,
        "median_warning_lead_time_min": round(float(median(lead_times)), 2) if lead_times else None,
    }


def relative_pr_auc_improvement(baseline: float | None, model: float | None) -> float | None:
    if baseline is None or model is None or baseline == 0:
        return None
    return round((model - baseline) / baseline, 4)


def classification_report(y_true: list[int], scores: list[float], threshold: float) -> dict[str, object]:
    y_hat = apply_threshold(scores, threshold)
    report: dict[str, object] = {}
    report.update(ranking_metrics(y_true, scores))
    report.update(operating_metrics(y_true, y_hat))
    report["threshold"] = threshold
    return report
