"""Sanitize reviewer output. Candidates stay numeric-authoritative."""

from __future__ import annotations

from app.optimization.contracts import (
    ConstraintCode,
    OptimizationReview,
    OptimizerId,
    ReviewStatus,
    payload_contains_forbidden_numeric_facts,
)
from app.optimization.registry import get_spec


def sanitize_review(
    review: OptimizationReview,
    *,
    candidate_ids: list[str],
    known_evidence_ids: list[str],
    optimization_pass: int,
    allowed_constraints: list[ConstraintCode],
) -> tuple[OptimizationReview, list[str]]:
    rejected: list[str] = []
    known_ids = set(candidate_ids)
    known_evidence = set(known_evidence_ids)
    preferred = []
    for item in review.preferred_candidate_ids:
        if item in known_ids:
            if item not in preferred:
                preferred.append(item)
        else:
            rejected.append(f"preferred:{item}")
    evidence = []
    for item in review.relevant_evidence_ids:
        if item in known_evidence:
            evidence.append(item)
        else:
            rejected.append(f"evidence:{item}")
    constraints: list[ConstraintCode] = []
    allowed = set(allowed_constraints)
    for item in review.requested_constraint_checks:
        if item in allowed:
            if item not in constraints:
                constraints.append(item)
        else:
            rejected.append(f"constraint:{item.value if hasattr(item, 'value') else item}")
    optimizer_ids: list[OptimizerId] = []
    for item in review.requested_optimizer_ids:
        try:
            spec = get_spec(item)
        except (KeyError, ValueError):
            rejected.append(f"optimizer:{item}")
            continue
        if spec.optimizer_id not in optimizer_ids:
            optimizer_ids.append(spec.optimizer_id)
        if len(optimizer_ids) >= 2:
            break
    status = review.status
    if status == ReviewStatus.REOPTIMIZE and optimization_pass >= 1:
        status = ReviewStatus.APPROVED_WITH_CAUTION
        rejected.append("reoptimize_coerced_pass_limit")
    sanitized = review.model_copy(
        update={
            "status": status,
            "preferred_candidate_ids": preferred,
            "relevant_evidence_ids": evidence,
            "requested_constraint_checks": constraints,
            "requested_optimizer_ids": optimizer_ids,
        }
    )
    dumped = sanitized.model_dump(mode="json")
    if payload_contains_forbidden_numeric_facts(dumped):
        # Reviewer schema has no numeric operational fields; strip if a summary smuggled keys via dump.
        rejected.append("forbidden_numeric_keys")
    return sanitized, rejected
