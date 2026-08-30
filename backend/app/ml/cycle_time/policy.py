"""Cycle-time V1 serving and promotion policy.

The official V1 predictor is a deterministic hierarchical median:
truck → route → global.

HGB is trained and stored as an experimental benchmark. It is promoted only
when validation MAE improves on the best deterministic baseline by at least
MIN_ML_RELATIVE_MAE_IMPROVEMENT. The test set is never used for this decision.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ml.cycle_time.contracts import (
    DETERMINISTIC_SERVED_PREDICTOR,
    MIN_ML_RELATIVE_MAE_IMPROVEMENT,
    ModelStatus,
)
from app.ml.cycle_time.evaluation import improvement

DETERMINISTIC_FALLBACK_ORDER = ("truck", "route", "global")


@dataclass(frozen=True)
class ServingDecision:
    served_predictor: str
    model_status: ModelStatus
    ml_promoted: bool
    best_baseline: str
    best_baseline_mae: float
    hgb_mae: float
    absolute_mae_improvement: float
    relative_mae_improvement: float | None
    promotion_threshold: float
    decision_reason: str
    hgb_role: str

    def metadata(self) -> dict[str, object]:
        return {
            "best_baseline": self.best_baseline,
            "best_baseline_validation_mae": self.best_baseline_mae,
            "hgb_validation_mae": self.hgb_mae,
            "absolute_mae_improvement": self.absolute_mae_improvement,
            "relative_mae_improvement": self.relative_mae_improvement,
            "promotion_threshold": self.promotion_threshold,
            "ml_promoted": self.ml_promoted,
            "served_predictor": self.served_predictor,
            "decision_reason": self.decision_reason,
            "deterministic_strategy": DETERMINISTIC_SERVED_PREDICTOR,
            "deterministic_fallback_order": list(DETERMINISTIC_FALLBACK_ORDER),
            "hgb_role": self.hgb_role,
        }


def _best_baseline_name(deterministic_val_mae: dict[str, float]) -> str:
    """Lowest validation MAE; official hierarchical name wins ties."""

    def key(name: str) -> tuple[float, int, str]:
        official = 0 if name == DETERMINISTIC_SERVED_PREDICTOR else 1
        return (float(deterministic_val_mae[name]), official, name)

    return min(deterministic_val_mae, key=key)


def select_served_predictor(
    hgb_val_mae: float,
    deterministic_val_mae: dict[str, float],
    *,
    threshold: float = MIN_ML_RELATIVE_MAE_IMPROVEMENT,
) -> ServingDecision:
    """Choose the served predictor from validation MAE only.

    `deterministic_val_mae` must not include test-set scores.
    """
    if not deterministic_val_mae:
        raise ValueError("At least one deterministic validation MAE is required.")
    best_baseline = _best_baseline_name(deterministic_val_mae)
    best_mae = float(deterministic_val_mae[best_baseline])
    delta = improvement(best_mae, hgb_val_mae)
    relative_reported = delta["relative_mae"]
    absolute = float(delta["absolute_mae"] or 0.0)
    raw_relative = (best_mae - hgb_val_mae) / best_mae if best_mae else None
    meets_threshold = raw_relative is not None and raw_relative >= threshold
    if hgb_val_mae < best_mae and meets_threshold:
        return ServingDecision(
            served_predictor="hgb",
            model_status=ModelStatus.MODEL_BEATS_BASELINE,
            ml_promoted=True,
            best_baseline=best_baseline,
            best_baseline_mae=best_mae,
            hgb_mae=hgb_val_mae,
            absolute_mae_improvement=absolute,
            relative_mae_improvement=relative_reported,
            promotion_threshold=threshold,
            decision_reason=(
                "HGB validation MAE improves on the best deterministic baseline "
                "by at least the minimum promotion threshold"
            ),
            hgb_role="served",
        )
    if hgb_val_mae < best_mae:
        reason = "ML improvement below minimum promotion threshold"
    else:
        reason = "HGB did not beat the best deterministic baseline on validation MAE"
    return ServingDecision(
        served_predictor=DETERMINISTIC_SERVED_PREDICTOR,
        model_status=ModelStatus.BASELINE_NOT_BEATEN,
        ml_promoted=False,
        best_baseline=best_baseline,
        best_baseline_mae=best_mae,
        hgb_mae=hgb_val_mae,
        absolute_mae_improvement=absolute,
        relative_mae_improvement=relative_reported,
        promotion_threshold=threshold,
        decision_reason=reason,
        hgb_role="experimental",
    )
