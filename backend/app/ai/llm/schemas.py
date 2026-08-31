"""Structured LLM output schemas.

These are aliases of the public contracts so validation is identical at the
provider, graph and API boundaries.
"""

from app.ai.contracts import DiagnosisResult, InvestigationConclusion, InvestigationRecommendation, RecommendationDiscussionReply

__all__ = ["DiagnosisResult", "InvestigationConclusion", "InvestigationRecommendation", "RecommendationDiscussionReply"]
