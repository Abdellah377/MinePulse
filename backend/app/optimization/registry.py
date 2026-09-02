"""Frozen optimizer registry. Planner may choose only these IDs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.optimization.contracts import ConstraintCode, ObjectiveProfile, OptimizerId, ProblemType
from app.optimization.engines import dispatch_loader, route

DISPATCH_PROBLEMS = frozenset(
    {
        ProblemType.CONGESTION_RISK,
        ProblemType.PROLONGED_LOADING_WAIT,
        ProblemType.QUEUE_IMBALANCE,
        ProblemType.DISPATCH_CYCLE_DELAY,
        ProblemType.PRODUCTION_FLOW_DISPATCH,
    }
)
ROUTE_PROBLEMS = frozenset(
    {
        ProblemType.ROAD_BLOCKAGE,
        ProblemType.ROUTE_CONGESTION,
        ProblemType.RESTRICTED_ROUTE,
        ProblemType.CONGESTION_RISK,
        ProblemType.DISPATCH_CYCLE_DELAY,
    }
)
DISPATCH_OBJECTIVES = frozenset(
    {
        ObjectiveProfile.REDUCE_WAITING_TIME,
        ObjectiveProfile.REDUCE_CYCLE_DELAY,
        ObjectiveProfile.BALANCE_LOADING_POINTS,
    }
)
ROUTE_OBJECTIVES = frozenset(
    {
        ObjectiveProfile.MINIMIZE_TRAVEL_TIME,
        ObjectiveProfile.MINIMIZE_DISTANCE,
        ObjectiveProfile.AVOID_RESTRICTED_ROADS,
    }
)
SHARED_CONSTRAINTS = frozenset(
    {
        ConstraintCode.EXCLUDE_UNAVAILABLE_EQUIPMENT,
        ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK,
        ConstraintCode.REQUIRE_ROUTABLE_PATH,
        ConstraintCode.EXCLUDE_CLOSED_ROADS,
        ConstraintCode.AVOID_RESTRICTED_ROADS_WHEN_ALTERNATIVE_EXISTS,
    }
)


@dataclass(frozen=True)
class OptimizerSpec:
    optimizer_id: OptimizerId
    version: str
    supported_problem_types: frozenset[ProblemType]
    allowed_objectives: frozenset[ObjectiveProfile]
    allowed_constraint_codes: frozenset[ConstraintCode]
    execute: Callable[..., list[dict]]


REGISTRY: dict[OptimizerId, OptimizerSpec] = {
    OptimizerId.DISPATCH_LOADER: OptimizerSpec(
        optimizer_id=OptimizerId.DISPATCH_LOADER,
        version=dispatch_loader.ENGINE_VERSION,
        supported_problem_types=DISPATCH_PROBLEMS,
        allowed_objectives=DISPATCH_OBJECTIVES,
        allowed_constraint_codes=SHARED_CONSTRAINTS,
        execute=dispatch_loader.execute,
    ),
    OptimizerId.ROUTE: OptimizerSpec(
        optimizer_id=OptimizerId.ROUTE,
        version=route.ENGINE_VERSION,
        supported_problem_types=ROUTE_PROBLEMS,
        allowed_objectives=ROUTE_OBJECTIVES,
        allowed_constraint_codes=SHARED_CONSTRAINTS,
        execute=route.execute,
    ),
}


def get_spec(optimizer_id: OptimizerId | str) -> OptimizerSpec:
    key = optimizer_id if isinstance(optimizer_id, OptimizerId) else OptimizerId(optimizer_id)
    spec = REGISTRY.get(key)
    if spec is None:
        raise KeyError(f"Unknown optimizer: {optimizer_id}")
    return spec


def catalog_for_planner() -> list[dict[str, Any]]:
    return [
        {
            "optimizerId": spec.optimizer_id.value,
            "version": spec.version,
            "supportedProblemTypes": [item.value for item in spec.supported_problem_types],
            "allowedObjectives": [item.value for item in spec.allowed_objectives],
            "allowedConstraintCodes": [item.value for item in spec.allowed_constraint_codes],
        }
        for spec in REGISTRY.values()
    ]


def validate_selection(
    optimizer_ids: list[OptimizerId],
    problem_type: ProblemType | None,
    objectives: list[ObjectiveProfile],
    constraints: list[ConstraintCode],
) -> tuple[list[OptimizerId], list[ObjectiveProfile], list[ConstraintCode], list[str]]:
    """Keep only registered ids and engine-allowed objectives/constraints."""
    rejected: list[str] = []
    valid_ids: list[OptimizerId] = []
    for item in optimizer_ids:
        try:
            spec = get_spec(item)
        except (KeyError, ValueError):
            rejected.append(str(item))
            continue
        if problem_type is not None and problem_type not in spec.supported_problem_types:
            rejected.append(f"{spec.optimizer_id.value}:unsupported_problem")
            continue
        if spec.optimizer_id not in valid_ids:
            valid_ids.append(spec.optimizer_id)
        if len(valid_ids) >= 2:
            break
    allowed_obj = set()
    allowed_con = set()
    for optimizer_id in valid_ids:
        spec = get_spec(optimizer_id)
        allowed_obj |= spec.allowed_objectives
        allowed_con |= spec.allowed_constraint_codes
    kept_obj: list[ObjectiveProfile] = []
    for item in objectives:
        if item in allowed_obj:
            if item not in kept_obj:
                kept_obj.append(item)
        else:
            rejected.append(f"objective:{item.value if hasattr(item, 'value') else item}")
    kept_con: list[ConstraintCode] = []
    for item in constraints:
        if item in allowed_con:
            if item not in kept_con:
                kept_con.append(item)
        else:
            rejected.append(f"constraint:{item.value if hasattr(item, 'value') else item}")
    return valid_ids, kept_obj, kept_con, rejected
