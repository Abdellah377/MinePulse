"""Compose engines and finalize 1–3 visible recommendations. No LLM score blending."""

from __future__ import annotations

from typing import Any

from app.optimization.constraints import apply_loader_constraints, apply_path_constraints
from app.optimization.contracts import (
    CandidateRelation,
    ConstraintCode,
    ObjectiveProfile,
    OptimizerId,
    ReviewStatus,
    WorkflowStatus,
)
from app.optimization.engines.dispatch_loader import execute as execute_dispatch
from app.optimization.engines.route import execute as execute_route
from app.optimization.solver import DEFAULT_WEIGHTS, _rank_key

MAX_COMPOSED_CANDIDATES = 12
MAX_VISIBLE_RECOMMENDATIONS = 3
ORCHESTRATOR_VERSION = "1.0.0"
NO_CHANGE_OPERATOR_COPY = (
    "Aucune modification recommandée — le plan actuel reste le meilleur parmi les options évaluées."
)
REVIEW_UNAVAILABLE_COPY = "Résultats calculés — revue IA indisponible."
DETERMINISTIC_ONLY_COPY = "Résultats calculés — orchestration IA indisponible, plan déterministe conservé."


def execute_selected_engines(
    *,
    trusted: dict[str, Any],
    optimizer_ids: list[OptimizerId],
    objectives: list[ObjectiveProfile],
    constraints: list[ConstraintCode],
) -> list[dict]:
    """One generate_candidates pass. Dual DISPATCH+ROUTE does not multiply scores."""
    loaders = list(trusted.get("loaders") or [])
    loaders = apply_loader_constraints(
        loaders,
        constraints=constraints,
        mechanical_risk_loader_ids=set(trusted.get("mechanical_risk_loader_ids") or []),
    )
    ids = list(dict.fromkeys(optimizer_ids))[:2]
    if OptimizerId.ROUTE in ids and OptimizerId.DISPATCH_LOADER not in ids:
        candidates = execute_route(trusted=trusted, loaders=loaders)
    else:
        candidates = execute_dispatch(trusted=trusted, loaders=loaders)
    candidates = apply_path_constraints(candidates, constraints)
    candidates = apply_objective_policy(candidates, objectives)
    return candidates[:MAX_COMPOSED_CANDIDATES]


def apply_objective_policy(candidates: list[dict], objectives: list[ObjectiveProfile]) -> list[dict]:
    """Ranking/filter policies are explicit in code. Scores keep DEFAULT_WEIGHTS math."""
    rows = list(candidates)
    if ObjectiveProfile.AVOID_RESTRICTED_ROADS in objectives:
        rows = apply_path_constraints(rows, [ConstraintCode.AVOID_RESTRICTED_ROADS_WHEN_ALTERNATIVE_EXISTS])

    def metric(row: dict, key: str) -> tuple:
        value = row.get(key)
        return (0 if value is not None else 1, value if value is not None else 0.0, _rank_key(row))

    primary = next((item for item in objectives if item != ObjectiveProfile.AVOID_RESTRICTED_ROADS), None)
    if primary == ObjectiveProfile.MINIMIZE_DISTANCE:
        rows.sort(key=lambda row: metric(row, "distanceKm"))
    elif primary == ObjectiveProfile.MINIMIZE_TRAVEL_TIME:
        rows.sort(key=lambda row: metric(row, "travelMinutes"))
    elif primary in {ObjectiveProfile.REDUCE_WAITING_TIME, ObjectiveProfile.BALANCE_LOADING_POINTS}:
        rows.sort(key=lambda row: metric(row, "waitMinutes"))
    else:
        rows.sort(key=_rank_key)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def is_operationally_distinct(candidate: dict, baseline: dict | None) -> bool:
    if baseline is None:
        return True
    if candidate.get("loaderId") != baseline.get("loaderId"):
        return True
    return tuple(candidate.get("roadIds") or []) != tuple(baseline.get("roadIds") or [])


def _fingerprint(row: dict) -> tuple:
    return (row.get("loaderId"), tuple(row.get("roadIds") or []), row.get("destZoneCode"))


def classify_relation(candidate: dict, baseline: dict | None) -> CandidateRelation:
    if baseline is not None and _fingerprint(candidate) == _fingerprint(baseline):
        return CandidateRelation.BASELINE
    if baseline is None or candidate.get("score") is None or baseline.get("score") is None:
        return CandidateRelation.TRADEOFF
    if candidate["score"] < baseline["score"]:
        return CandidateRelation.IMPROVEMENT
    if candidate["score"] == baseline["score"] and is_operationally_distinct(candidate, baseline):
        return CandidateRelation.EQUIVALENT
    return CandidateRelation.TRADEOFF


def equivalent_group_id(score: float | None) -> str | None:
    if score is None:
        return None
    return f"eq-{score}"


def finalize_recommendations(
    candidates: list[dict],
    *,
    preferred_ids: list[str] | None = None,
    review_status: ReviewStatus | None = None,
) -> dict:
    """Visible recs: 0→NO_CHANGE, 1–3 real options. Never pad. Baseline is internal only."""
    preferred = [item for item in (preferred_ids or []) if any(row.get("candidateId") == item for row in candidates)]
    baseline = next((row for row in candidates if row.get("isCurrent")), None)
    stamped = []
    for row in candidates:
        relation = classify_relation(row, baseline)
        item = dict(row)
        item["candidateRelation"] = relation.value
        item["equivalentGroupId"] = (
            equivalent_group_id(row.get("score")) if relation == CandidateRelation.EQUIVALENT else None
        )
        stamped.append(item)

    improvements = [row for row in stamped if row["candidateRelation"] == CandidateRelation.IMPROVEMENT]
    equivalents = [row for row in stamped if row["candidateRelation"] == CandidateRelation.EQUIVALENT]
    displayed: list[dict] = []
    seen: set[tuple] = set()

    def take(row: dict) -> None:
        key = _fingerprint(row)
        if key in seen or len(displayed) >= MAX_VISIBLE_RECOMMENDATIONS:
            return
        if row["candidateRelation"] == CandidateRelation.BASELINE:
            return
        if row["candidateRelation"] == CandidateRelation.EQUIVALENT and not is_operationally_distinct(row, baseline):
            return
        seen.add(key)
        displayed.append(row)

    for row in improvements:
        take(row)
    if not displayed:
        for row in equivalents:
            take(row)
    elif len(displayed) < MAX_VISIBLE_RECOMMENDATIONS:
        for row in equivalents:
            if is_operationally_distinct(row, displayed[0]):
                take(row)

    if review_status == ReviewStatus.APPROVED_WITH_CAUTION:
        for candidate_id in preferred:
            match = next((row for row in stamped if row.get("candidateId") == candidate_id), None)
            if match is None:
                continue
            if match["candidateRelation"] == CandidateRelation.BASELINE:
                continue
            take(match)

    if not displayed:
        return {
            "candidates": stamped,
            "displayed": [],
            "displayedCandidateIds": [],
            "baselineCandidateId": baseline.get("candidateId") if baseline else None,
            "recommendedCandidateId": baseline.get("candidateId") if baseline else None,
            "workflowStatus": WorkflowStatus.NO_CHANGE_RECOMMENDED.value,
            "weights": dict(DEFAULT_WEIGHTS),
        }
    return {
        "candidates": stamped,
        "displayed": displayed,
        "displayedCandidateIds": [row["candidateId"] for row in displayed],
        "baselineCandidateId": baseline.get("candidateId") if baseline else None,
        "recommendedCandidateId": displayed[0]["candidateId"],
        "workflowStatus": WorkflowStatus.ORCHESTRATED.value,
        "weights": dict(DEFAULT_WEIGHTS),
    }
