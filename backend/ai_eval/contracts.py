"""Serializable contracts for investigation evaluation and reporting."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.ai.contracts import (
    ConfidenceLevel,
    EvidenceKind,
    EvidenceRequestType,
    InvestigationTrigger,
    TriggerType,
)


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class GroundTruthLabel(str, Enum):
    MECHANICAL_FAILURE = "MECHANICAL_FAILURE"
    CONNECTIVITY_LOSS = "CONNECTIVITY_LOSS"
    UNEXPLAINED_STOP = "UNEXPLAINED_STOP"


class EvaluationOutcome(str, Enum):
    PASS = "PASS"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    AI_REASONING_FAILURE = "AI_REASONING_FAILURE"
    MISSING_OPERATIONAL_DATA = "MISSING_OPERATIONAL_DATA"
    DATA_QUALITY_WARNING = "DATA_QUALITY_WARNING"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INTEGRATION_FAILURE = "INTEGRATION_FAILURE"


class CheckCategory(str, Enum):
    PIPELINE = "PIPELINE"
    EVIDENCE = "EVIDENCE"
    ROOT_CAUSE_SAFETY = "ROOT_CAUSE_SAFETY"
    GROUND_TRUTH_ALIGNMENT = "GROUND_TRUTH_ALIGNMENT"
    CONTRADICTIONS = "CONTRADICTIONS"
    UNCERTAINTY = "UNCERTAINTY"
    RECOMMENDATION_SAFETY = "RECOMMENDATION_SAFETY"
    PROVENANCE = "PROVENANCE"
    DATA_QUALITY = "DATA_QUALITY"


class EvaluationGroundTruth(EvaluationModel):
    """Evaluator-only knowledge. It must never be serialized into a trigger."""

    label: GroundTruthLabel
    summary: str
    scenario_name: str | None = None
    reviewer_notes: str | None = None


class EvaluationCase(EvaluationModel):
    case_id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    equipment_code: str
    trigger_type: TriggerType
    ground_truth: EvaluationGroundTruth
    expected_evidence_tools: list[str] = Field(default_factory=list)
    expected_evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    # Every inner list is a group of equivalent words; one word per group must match.
    expected_concept_groups: list[list[str]] = Field(default_factory=list)
    forbidden_concepts: list[str] = Field(default_factory=list)
    expected_reliable_root_cause: bool | None = None
    expected_confidence: ConfidenceLevel | None = None
    inconclusive_acceptable: bool = False
    mock_request_type: EvidenceRequestType | None = None


class EvaluationCheck(EvaluationModel):
    check_id: str
    category: CheckCategory
    passed: bool
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceTrace(EvaluationModel):
    evidence_id: str
    kind: EvidenceKind
    source_tool: str
    source_service: str
    metric: str
    available: bool
    status: str
    source_record_ids: list[str] = Field(default_factory=list)


class EvaluationReport(EvaluationModel):
    case_id: str
    case_description: str
    trigger: InvestigationTrigger
    investigation_id: str | None = None
    provider: str | None = None
    model: str | None = None
    reasoning_mode: str
    status: str
    pipeline_correct: bool
    reasoning_checks_passed: int = 0
    reasoning_checks_total: int = 0
    outcome: EvaluationOutcome
    evidence: list[EvidenceTrace] = Field(default_factory=list)
    hypotheses: list[dict] = Field(default_factory=list)
    contradictions: list[dict] = Field(default_factory=list)
    missing_information: list[dict] = Field(default_factory=list)
    evidence_request_history: list[dict] = Field(default_factory=list)
    conclusion: dict | None = None
    root_cause_reliable: bool = False
    recommendation: dict | None = None
    iteration_count: int = 0
    checks: list[EvaluationCheck] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)
    failure_stage: str | None = None
    human_review_notes: str | None = None
