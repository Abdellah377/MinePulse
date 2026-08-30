"""Failure-Risk V1 serving and promotion policy.

Learned models are promoted only when validation PR-AUC improves on the best
deterministic baseline by at least MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT.
HGB is kept only if it also beats logistic by that margin. Test set unused.

PROTOTYPE / SYNTHETIC-DATA MODEL.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ml.failure_risk.contracts import MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT, ModelStatus
from app.ml.failure_risk.evaluation import relative_pr_auc_improvement


@dataclass(frozen=True)
class ServingDecision:
    served_predictor: str
    model_status: ModelStatus
    ml_promoted: bool
    best_baseline: str
    best_baseline_pr_auc: float | None
    logistic_pr_auc: float | None
    hgb_pr_auc: float | None
    selected_learned: str
    selected_learned_pr_auc: float | None
    relative_pr_auc_improvement: float | None
    promotion_threshold: float
    decision_reason: str

    def metadata(self) -> dict[str, object]:
        return {
            "best_baseline": self.best_baseline,
            "best_baseline_validation_pr_auc": self.best_baseline_pr_auc,
            "logistic_validation_pr_auc": self.logistic_pr_auc,
            "hgb_validation_pr_auc": self.hgb_pr_auc,
            "selected_learned": self.selected_learned,
            "selected_learned_validation_pr_auc": self.selected_learned_pr_auc,
            "relative_pr_auc_improvement": self.relative_pr_auc_improvement,
            "promotion_threshold": self.promotion_threshold,
            "ml_promoted": self.ml_promoted,
            "served_predictor": self.served_predictor,
            "decision_reason": self.decision_reason,
        }


def _best_name(scores: dict[str, float | None]) -> str:
    def key(name: str) -> tuple[float, str]:
        value = scores[name]
        return (float("-inf") if value is None else float(value), name)

    return max(scores, key=key)


def select_learned_model(
    logistic_pr_auc: float | None,
    hgb_pr_auc: float | None,
    *,
    threshold: float = MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT,
) -> tuple[str, float | None]:
    if hgb_pr_auc is None:
        return "logistic", logistic_pr_auc
    if logistic_pr_auc is None:
        return "hgb", hgb_pr_auc
    relative = relative_pr_auc_improvement(logistic_pr_auc, hgb_pr_auc)
    if relative is not None and relative >= threshold:
        return "hgb", hgb_pr_auc
    return "logistic", logistic_pr_auc


def select_served_predictor(
    *,
    logistic_pr_auc: float | None,
    hgb_pr_auc: float | None,
    baseline_pr_auc: dict[str, float | None],
    threshold: float = MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT,
) -> ServingDecision:
    if not baseline_pr_auc:
        raise ValueError("At least one baseline PR-AUC is required.")
    best_baseline = _best_name(baseline_pr_auc)
    best_baseline_score = baseline_pr_auc[best_baseline]
    learned_name, learned_score = select_learned_model(logistic_pr_auc, hgb_pr_auc, threshold=threshold)
    relative = relative_pr_auc_improvement(best_baseline_score, learned_score)
    promotes = (
        learned_score is not None
        and best_baseline_score is not None
        and learned_score > best_baseline_score
        and relative is not None
        and relative >= threshold
    )
    if promotes:
        return ServingDecision(
            served_predictor=learned_name,
            model_status=ModelStatus.MODEL_BEATS_BASELINE,
            ml_promoted=True,
            best_baseline=best_baseline,
            best_baseline_pr_auc=best_baseline_score,
            logistic_pr_auc=logistic_pr_auc,
            hgb_pr_auc=hgb_pr_auc,
            selected_learned=learned_name,
            selected_learned_pr_auc=learned_score,
            relative_pr_auc_improvement=relative,
            promotion_threshold=threshold,
            decision_reason=(
                "Selected learned model validation PR-AUC improves on the best "
                "deterministic baseline by at least the minimum promotion threshold"
            ),
        )
    if learned_score is not None and best_baseline_score is not None and learned_score > best_baseline_score:
        reason = "ML improvement below minimum promotion threshold"
    else:
        reason = "Learned models did not beat the best deterministic baseline on validation PR-AUC"
    return ServingDecision(
        served_predictor=best_baseline,
        model_status=ModelStatus.BASELINE_NOT_BEATEN,
        ml_promoted=False,
        best_baseline=best_baseline,
        best_baseline_pr_auc=best_baseline_score,
        logistic_pr_auc=logistic_pr_auc,
        hgb_pr_auc=hgb_pr_auc,
        selected_learned=learned_name,
        selected_learned_pr_auc=learned_score,
        relative_pr_auc_improvement=relative,
        promotion_threshold=threshold,
        decision_reason=reason,
    )
