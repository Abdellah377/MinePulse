"""Serializable contracts shared by the investigation graph, API and storage."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class TriggerType(str, Enum):
    AUTOMATIC_MONITORING = "AUTOMATIC_MONITORING"
    EXISTING_ALERT = "EXISTING_ALERT"
    USER_INVESTIGATE = "USER_INVESTIGATE"
    CHAT_REQUEST = "CHAT_REQUEST"


class InvestigationSubject(str, Enum):
    PRODUCTION = "PRODUCTION"
    EQUIPMENT = "EQUIPMENT"
    ZONE = "ZONE"
    CONNECTIVITY = "CONNECTIVITY"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class EvidenceKind(str, Enum):
    FACT = "FACT"
    DERIVED_METRIC = "DERIVED_METRIC"
    MODEL_PREDICTION = "MODEL_PREDICTION"


class ConfidenceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InvestigationStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVING_CONTEXT = "RESOLVING_CONTEXT"
    GATHERING_EVIDENCE = "GATHERING_EVIDENCE"
    ANALYZING = "ANALYZING"
    BUILDING_CONCLUSION = "BUILDING_CONCLUSION"
    BUILDING_RECOMMENDATION = "BUILDING_RECOMMENDATION"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_UNCERTAINTY = "COMPLETED_WITH_UNCERTAINTY"
    FAILED = "FAILED"


class EvidenceRequestType(str, Enum):
    SHIFT_PRODUCTION = "SHIFT_PRODUCTION"
    FLEET_SNAPSHOT = "FLEET_SNAPSHOT"
    CYCLE_PERFORMANCE = "CYCLE_PERFORMANCE"
    DOWNTIME = "DOWNTIME"
    SITE_ALERTS = "SITE_ALERTS"
    ASSIGNMENTS = "ASSIGNMENTS"
    EQUIPMENT_TIMELINE = "EQUIPMENT_TIMELINE"
    ZONE_CONTEXT = "ZONE_CONTEXT"
    OEM_CONNECTIVITY = "OEM_CONNECTIVITY"
    OEM_DIAGNOSTICS = "OEM_DIAGNOSTICS"
    OEM_ERRORS = "OEM_ERRORS"
    OEM_MAINTENANCE_INDICATORS = "OEM_MAINTENANCE_INDICATORS"


class RecommendationAction(str, Enum):
    INSPECT_EQUIPMENT = "INSPECT_EQUIPMENT"
    VERIFY_OPERATIONAL_CONDITION = "VERIFY_OPERATIONAL_CONDITION"
    REVIEW_QUEUE_DISTRIBUTION = "REVIEW_QUEUE_DISTRIBUTION"
    ESCALATE_TO_MAINTENANCE = "ESCALATE_TO_MAINTENANCE"
    CONSIDER_REASSIGNMENT = "CONSIDER_REASSIGNMENT"
    CONTINUE_MONITORING = "CONTINUE_MONITORING"
    NO_ACTION = "NO_ACTION"


class InvestigationTrigger(ContractModel):
    trigger_type: TriggerType
    subject: InvestigationSubject = InvestigationSubject.PRODUCTION
    source: Annotated[str, Field(min_length=1, max_length=120)]
    site_id: Annotated[int, Field(gt=0)]
    shift_id: Annotated[int, Field(gt=0)] | None = None
    equipment_id: Annotated[int, Field(gt=0)] | None = None
    zone_id: Annotated[int, Field(gt=0)] | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    severity: Severity | None = None
    source_record_id: str | None = Field(default=None, max_length=160)
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_aware_timestamp(self) -> "InvestigationTrigger":
        if self.occurred_at.tzinfo is None:
            self.occurred_at = self.occurred_at.replace(tzinfo=timezone.utc)
        return self


class ResolvedOperationalContext(ContractModel):
    site_id: int
    site_code: str
    site_name: str
    shift_id: int | None
    shift_name: str | None
    operational_now: datetime
    window_start: datetime
    window_end: datetime


class EvidenceItem(ContractModel):
    evidence_id: str = Field(default_factory=lambda: f"ev-{uuid4()}")
    kind: EvidenceKind
    source_tool: str
    source_service: str
    metric: str
    value: JsonValue = None
    available: bool = True
    unit: str | None = None
    site_id: int | None = None
    shift_id: int | None = None
    equipment_id: int | None = None
    zone_id: int | None = None
    observed_at: datetime | None = None
    source_record_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    notes: str | None = None

    @model_validator(mode="after")
    def unavailable_values_are_null(self) -> "EvidenceItem":
        if not self.available and self.value is not None:
            raise ValueError("unavailable evidence must have a null value")
        return self


class EvidenceRequest(ContractModel):
    request_id: str = Field(default_factory=lambda: f"req-{uuid4()}")
    request_type: EvidenceRequestType
    equipment_id: int | None = Field(default=None, gt=0)
    zone_id: int | None = Field(default=None, gt=0)
    start_time: datetime | None = None
    end_time: datetime | None = None
    parameters: list[str] = Field(default_factory=list, max_length=16)
    reason: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def valid_window(self) -> "EvidenceRequest":
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time must not precede start_time")
        return self


class Hypothesis(ContractModel):
    hypothesis_id: str = Field(default_factory=lambda: f"hyp-{uuid4()}")
    statement: str = Field(min_length=1, max_length=1200)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradictory_evidence_ids: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel
    rationale: str = Field(min_length=1, max_length=1600)


class Contradiction(ContractModel):
    description: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=2)


class DiagnosisResult(ContractModel):
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=8)
    requested_information: list[EvidenceRequest] = Field(default_factory=list, max_length=8)
    contradictions: list[Contradiction] = Field(default_factory=list, max_length=8)
    can_conclude: bool
    confidence: ConfidenceLevel
    confidence_rationale: str = Field(min_length=1, max_length=1600)
    reasoning_summary: str = Field(min_length=1, max_length=2400)


class InvestigationConclusion(ContractModel):
    summary: str = Field(min_length=1, max_length=2400)
    root_cause: str | None = Field(default=None, max_length=1200)
    reliable_root_cause: bool = False
    observed_fact_evidence_ids: list[str] = Field(default_factory=list)
    derived_metric_evidence_ids: list[str] = Field(default_factory=list)
    supported_hypothesis_ids: list[str] = Field(default_factory=list)
    unresolved_uncertainties: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel


class InvestigationRecommendation(ContractModel):
    action_type: RecommendationAction
    description: str = Field(min_length=1, max_length=1600)
    rationale: str = Field(min_length=1, max_length=1600)
    evidence_ids: list[str] = Field(default_factory=list)
    target_equipment_id: int | None = Field(default=None, gt=0)
    target_zone_id: int | None = Field(default=None, gt=0)
    operational_constraints: list[str] = Field(default_factory=list)
    human_validation_required: bool = True


class InvestigationError(ContractModel):
    stage: str
    error_type: str
    message: str


class InvestigationResult(ContractModel):
    investigation_id: UUID
    trigger: InvestigationTrigger
    operational_context: ResolvedOperationalContext | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    requested_information: list[EvidenceRequest] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    conclusion: InvestigationConclusion | None = None
    recommendation: InvestigationRecommendation | None = None
    iteration_count: int = 0
    max_iterations: int
    iteration_limit_reached: bool = False
    status: InvestigationStatus
    error: InvestigationError | None = None
    started_at: datetime
    completed_at: datetime | None = None
    graph_version: str
    provider: str
    model: str
