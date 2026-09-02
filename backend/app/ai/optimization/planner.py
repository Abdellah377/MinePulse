"""Sanitize planner decisions. Unknown engines and invented numbers are dropped."""

from __future__ import annotations

from typing import Any

from app.optimization.contracts import (
    ConstraintCode,
    ObjectiveProfile,
    OptimizationPlannerDecision,
    OptimizerId,
    ProblemType,
    payload_contains_forbidden_numeric_facts,
)
from app.optimization.registry import validate_selection

_ALERT_PROBLEM = {
    "CONGESTION_RISK": ProblemType.CONGESTION_RISK,
    "PRODUCTION_DEVIATION": ProblemType.PRODUCTION_FLOW_DISPATCH,
    "ROAD_CLOSED": ProblemType.ROAD_BLOCKAGE,
    "ZONE_CLOSED": ProblemType.ROAD_BLOCKAGE,
}
_DETECTOR_PROBLEM = {
    "prolonged-idle-wait": ProblemType.PROLONGED_LOADING_WAIT,
    "abnormal-cycle-duration": ProblemType.DISPATCH_CYCLE_DELAY,
}

ALWAYS_ON_CONSTRAINTS = (
    ConstraintCode.EXCLUDE_UNAVAILABLE_EQUIPMENT,
    ConstraintCode.REQUIRE_ROUTABLE_PATH,
    ConstraintCode.EXCLUDE_CLOSED_ROADS,
)


def default_problem_type(facts: dict[str, Any]) -> ProblemType:
    detector = str(facts.get("detectorId") or "")
    if detector in _DETECTOR_PROBLEM:
        return _DETECTOR_PROBLEM[detector]
    alert_type = str(facts.get("alertType") or "")
    return _ALERT_PROBLEM.get(alert_type, ProblemType.CONGESTION_RISK)


def strip_forbidden_numeric_keys(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: strip_forbidden_numeric_keys(value)
            for key, value in payload.items()
            if key not in {
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
        }
    if isinstance(payload, list):
        return [strip_forbidden_numeric_keys(item) for item in payload]
    return payload


def planner_payload_from_facts(facts: dict[str, Any]) -> dict[str, Any]:
    payload = strip_forbidden_numeric_keys(dict(facts))
    if payload_contains_forbidden_numeric_facts(payload):
        raise RuntimeError("planner payload must not include numeric optimizer inputs")
    return payload


def sanitize_planner_decision(
    decision: OptimizationPlannerDecision,
    *,
    facts: dict[str, Any],
) -> tuple[OptimizationPlannerDecision, list[str]]:
    allowed_evidence = {str(item) for item in (facts.get("evidenceIds") or [])}
    problem = decision.problem_type or default_problem_type(facts)
    optimizer_ids = list(decision.selected_optimizers)
    if not optimizer_ids:
        optimizer_ids = [OptimizerId.DISPATCH_LOADER]
        if facts.get("hasRoadRestrictionOrBlockage"):
            optimizer_ids.append(OptimizerId.ROUTE)
    valid_ids, objectives, constraints, rejected = validate_selection(
        optimizer_ids,
        problem,
        list(decision.objectives),
        list(decision.requested_constraint_checks),
    )
    if not valid_ids:
        valid_ids = [OptimizerId.DISPATCH_LOADER]
        rejected.append("defaulted_dispatch_loader")
        _, objectives, constraints, extra = validate_selection(
            valid_ids, None, list(decision.objectives), list(decision.requested_constraint_checks)
        )
        rejected.extend(extra)
    if not objectives:
        if OptimizerId.ROUTE in valid_ids and OptimizerId.DISPATCH_LOADER not in valid_ids:
            objectives = [ObjectiveProfile.MINIMIZE_TRAVEL_TIME]
        else:
            objectives = [ObjectiveProfile.REDUCE_WAITING_TIME]
    merged_constraints: list[ConstraintCode] = []
    for item in (*ALWAYS_ON_CONSTRAINTS, *constraints):
        if item not in merged_constraints:
            merged_constraints.append(item)
    evidence = [item for item in decision.relevant_evidence_ids if str(item) in allowed_evidence]
    for item in decision.relevant_evidence_ids:
        if str(item) not in allowed_evidence:
            rejected.append(f"evidence:{item}")
    sanitized = decision.model_copy(
        update={
            "problem_type": problem,
            "selected_optimizers": valid_ids[:2],
            "objectives": objectives,
            "requested_constraint_checks": merged_constraints,
            "relevant_evidence_ids": evidence,
            "optimization_applicable": True if valid_ids else decision.optimization_applicable,
        }
    )
    dumped = sanitized.model_dump(mode="json")
    if payload_contains_forbidden_numeric_facts(dumped):
        raise RuntimeError("sanitized planner decision must not include numeric optimizer inputs")
    return sanitized, rejected
