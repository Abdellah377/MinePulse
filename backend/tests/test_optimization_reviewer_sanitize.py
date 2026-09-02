from app.ai.optimization.reviewer import sanitize_review
from app.optimization.contracts import ConstraintCode, OptimizationReview, OptimizerId, ReviewStatus


def test_reviewer_drops_unknown_preferred_ids_and_cannot_loop_on_second_pass():
    review = OptimizationReview(
        status=ReviewStatus.REOPTIMIZE,
        preferred_candidate_ids=["c-2", "invented"],
        relevant_evidence_ids=["alert-1", "fake"],
        requested_constraint_checks=[ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK],
        requested_optimizer_ids=[OptimizerId.ROUTE],
        reoptimization_reason="check mechanical risk",
    )
    sanitized, rejected = sanitize_review(
        review,
        candidate_ids=["c-1", "c-2"],
        known_evidence_ids=["alert-1"],
        optimization_pass=1,
        allowed_constraints=list(ConstraintCode),
    )
    assert sanitized.status == ReviewStatus.APPROVED_WITH_CAUTION
    assert sanitized.preferred_candidate_ids == ["c-2"]
    assert sanitized.relevant_evidence_ids == ["alert-1"]
    assert "reoptimize_coerced_pass_limit" in rejected
    assert "invented" not in sanitized.preferred_candidate_ids


def test_reviewer_allows_reoptimize_on_first_pass_with_registered_engine():
    review = OptimizationReview(
        status=ReviewStatus.REOPTIMIZE,
        requested_optimizer_ids=[OptimizerId.ROUTE],
        requested_constraint_checks=[ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK],
        reoptimization_reason="restricted road",
    )
    sanitized, rejected = sanitize_review(
        review,
        candidate_ids=["c-1"],
        known_evidence_ids=[],
        optimization_pass=0,
        allowed_constraints=list(ConstraintCode),
    )
    assert sanitized.status == ReviewStatus.REOPTIMIZE
    assert sanitized.requested_optimizer_ids == [OptimizerId.ROUTE]
    assert ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK in sanitized.requested_constraint_checks
    assert "reoptimize_coerced_pass_limit" not in rejected
