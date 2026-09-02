"""Typed optimization orchestration contracts. No LLM. No numeric invention."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class OptimizerId(str, Enum):
    DISPATCH_LOADER = "DISPATCH_LOADER"
    ROUTE = "ROUTE"


class ProblemType(str, Enum):
    CONGESTION_RISK = "CONGESTION_RISK"
    PROLONGED_LOADING_WAIT = "PROLONGED_LOADING_WAIT"
    QUEUE_IMBALANCE = "QUEUE_IMBALANCE"
    DISPATCH_CYCLE_DELAY = "DISPATCH_CYCLE_DELAY"
    PRODUCTION_FLOW_DISPATCH = "PRODUCTION_FLOW_DISPATCH"
    ROAD_BLOCKAGE = "ROAD_BLOCKAGE"
    ROUTE_CONGESTION = "ROUTE_CONGESTION"
    RESTRICTED_ROUTE = "RESTRICTED_ROUTE"


class ObjectiveProfile(str, Enum):
    REDUCE_WAITING_TIME = "REDUCE_WAITING_TIME"
    REDUCE_CYCLE_DELAY = "REDUCE_CYCLE_DELAY"
    BALANCE_LOADING_POINTS = "BALANCE_LOADING_POINTS"
    MINIMIZE_TRAVEL_TIME = "MINIMIZE_TRAVEL_TIME"
    MINIMIZE_DISTANCE = "MINIMIZE_DISTANCE"
    AVOID_RESTRICTED_ROADS = "AVOID_RESTRICTED_ROADS"


class ConstraintCode(str, Enum):
    EXCLUDE_UNAVAILABLE_EQUIPMENT = "EXCLUDE_UNAVAILABLE_EQUIPMENT"
    EXCLUDE_CRITICAL_MECHANICAL_RISK = "EXCLUDE_CRITICAL_MECHANICAL_RISK"
    REQUIRE_ROUTABLE_PATH = "REQUIRE_ROUTABLE_PATH"
    EXCLUDE_CLOSED_ROADS = "EXCLUDE_CLOSED_ROADS"
    AVOID_RESTRICTED_ROADS_WHEN_ALTERNATIVE_EXISTS = "AVOID_RESTRICTED_ROADS_WHEN_ALTERNATIVE_EXISTS"


class ReviewStatus(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_WITH_CAUTION = "APPROVED_WITH_CAUTION"
    REOPTIMIZE = "REOPTIMIZE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class WorkflowStatus(str, Enum):
    ORCHESTRATED = "ORCHESTRATED"
    DETERMINISTIC_ONLY = "DETERMINISTIC_ONLY"
    REVIEW_UNAVAILABLE = "REVIEW_UNAVAILABLE"
    NO_CHANGE_RECOMMENDED = "NO_CHANGE_RECOMMENDED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CandidateRelation(str, Enum):
    BASELINE = "BASELINE"
    IMPROVEMENT = "IMPROVEMENT"
    EQUIVALENT = "EQUIVALENT"
    TRADEOFF = "TRADEOFF"


class OptimizationConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


FORBIDDEN_PLANNER_NUMERIC_KEYS = frozenset(
    {
        "waitMinutes",
        "waitingMinutes",
        "travelMinutes",
        "distanceKm",
        "score",
        "waitingTruckCount",
        "queueCount",
        "coordinates",
        "lat",
        "lon",
        "w_travel",
        "w_wait",
        "weights",
    }
)


class OptimizationPlannerDecision(ContractModel):
    optimization_applicable: bool = True
    problem_type: ProblemType = ProblemType.CONGESTION_RISK
    subject_equipment_id: int | None = None
    zone_id: int | None = None
    selected_optimizers: list[OptimizerId] = Field(default_factory=list)
    objectives: list[ObjectiveProfile] = Field(default_factory=list)
    relevant_evidence_ids: list[str] = Field(default_factory=list)
    requested_constraint_checks: list[ConstraintCode] = Field(default_factory=list)
    planner_summary: str = ""
    confidence: OptimizationConfidence = OptimizationConfidence.MEDIUM

    @field_validator("selected_optimizers")
    @classmethod
    def _cap_optimizers(cls, value: list[OptimizerId]) -> list[OptimizerId]:
        unique: list[OptimizerId] = []
        for item in value:
            if item not in unique:
                unique.append(item)
        return unique[:2]


class ReviewIssue(ContractModel):
    code: str = ""
    detail: str = ""


class OptimizationReview(ContractModel):
    status: ReviewStatus = ReviewStatus.APPROVED
    issues: list[ReviewIssue] = Field(default_factory=list)
    preferred_candidate_ids: list[str] = Field(default_factory=list)
    relevant_evidence_ids: list[str] = Field(default_factory=list)
    requested_constraint_checks: list[ConstraintCode] = Field(default_factory=list)
    requested_optimizer_ids: list[OptimizerId] = Field(default_factory=list)
    operator_summary: str = ""
    caution_summary: str = ""
    reoptimization_reason: str = ""


def payload_contains_forbidden_numeric_facts(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_PLANNER_NUMERIC_KEYS:
                return True
            if payload_contains_forbidden_numeric_facts(value):
                return True
        return False
    if isinstance(payload, list):
        return any(payload_contains_forbidden_numeric_facts(item) for item in payload)
    return False
