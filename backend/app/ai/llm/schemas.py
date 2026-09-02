"""Structured LLM output schemas.

These are aliases of the public contracts so validation is identical at the
provider, graph and API boundaries.
"""

from app.ai.contracts import DiagnosisResult, InvestigationConclusion, InvestigationRecommendation, RecommendationDiscussionReply
from app.optimization.contracts import OptimizationPlannerDecision, OptimizationReview

__all__ = [
    "DiagnosisResult",
    "InvestigationConclusion",
    "InvestigationRecommendation",
    "RecommendationDiscussionReply",
    "OptimizationPlannerDecision",
    "OptimizationReview",
]
