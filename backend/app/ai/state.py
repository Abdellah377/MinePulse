"""Temporary LangGraph working memory for one investigation."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from app.ai.contracts import (
    Contradiction,
    DiagnosisResult,
    EvidenceItem,
    EvidenceRequest,
    EvidenceRequestAttempt,
    Hypothesis,
    InvestigationConclusion,
    InvestigationError,
    InvestigationRecommendation,
    InvestigationStatus,
    InvestigationTrigger,
    ResolvedOperationalContext,
)


class InvestigationState(TypedDict):
    investigation_id: str
    trigger: InvestigationTrigger
    operational_context: ResolvedOperationalContext | None
    evidence: list[EvidenceItem]
    diagnosis: DiagnosisResult | None
    hypotheses: list[Hypothesis]
    requested_information: list[EvidenceRequest]
    evidence_request_history: list[EvidenceRequestAttempt]
    contradictions: list[Contradiction]
    conclusion: InvestigationConclusion | None
    recommendation: InvestigationRecommendation | None
    iteration_count: int
    max_iterations: int
    iteration_limit_reached: bool
    evidence_expansion_exhausted: bool
    status: InvestigationStatus
    error: InvestigationError | None
    started_at: datetime
    completed_at: datetime | None
    graph_version: str
    provider: str
    model: str
