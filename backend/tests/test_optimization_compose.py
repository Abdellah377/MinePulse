from app.optimization.compose import classify_relation, finalize_recommendations
from app.optimization.contracts import CandidateRelation, ObjectiveProfile, ReviewStatus


def _row(**overrides):
    base = {
        "candidateId": "c-1",
        "loaderId": 10,
        "loaderCode": "LD-1",
        "destZoneCode": "D1",
        "roadIds": ["R-1"],
        "distanceKm": 4.0,
        "travelMinutes": 8.0,
        "waitMinutes": 6.0,
        "score": 14.0,
        "constraintNotes": [],
        "isCurrent": False,
        "rankReason": "score",
    }
    base.update(overrides)
    return base


def test_minimize_distance_finalization_uses_distance_not_score():
    baseline = _row(candidateId="now", isCurrent=True, distanceKm=5.0, score=4.0, loaderId=10)
    shorter = _row(candidateId="near", distanceKm=2.0, score=20.0, loaderId=11, roadIds=["R-2"])
    relation = classify_relation(shorter, baseline, [ObjectiveProfile.MINIMIZE_DISTANCE])
    assert relation == CandidateRelation.IMPROVEMENT
    result = finalize_recommendations(
        [baseline, shorter],
        objectives=[ObjectiveProfile.MINIMIZE_DISTANCE],
    )
    assert result["displayedCandidateIds"] == ["near"]
    assert result["recommendedCandidateId"] == "near"


def test_minimize_travel_time_finalization_uses_travel_not_score():
    baseline = _row(candidateId="now", isCurrent=True, travelMinutes=10.0, score=5.0)
    faster = _row(candidateId="fast", travelMinutes=3.0, score=18.0, loaderId=11, roadIds=["R-2"])
    result = finalize_recommendations(
        [baseline, faster],
        objectives=[ObjectiveProfile.MINIMIZE_TRAVEL_TIME],
    )
    assert classify_relation(faster, baseline, [ObjectiveProfile.MINIMIZE_TRAVEL_TIME]) == CandidateRelation.IMPROVEMENT
    assert result["displayedCandidateIds"] == ["fast"]


def test_reduce_waiting_time_finalization_uses_wait_not_score():
    baseline = _row(candidateId="now", isCurrent=True, waitMinutes=9.3, score=4.7)
    idle = _row(candidateId="idle", waitMinutes=0.0, score=12.0, loaderId=11, roadIds=["R-2"])
    result = finalize_recommendations(
        [baseline, idle],
        objectives=[ObjectiveProfile.REDUCE_WAITING_TIME],
    )
    assert classify_relation(idle, baseline, [ObjectiveProfile.REDUCE_WAITING_TIME]) == CandidateRelation.IMPROVEMENT
    assert result["displayedCandidateIds"] == ["idle"]


def test_balance_loading_points_matches_waiting_time_policy():
    baseline = _row(candidateId="now", isCurrent=True, waitMinutes=8.0, score=3.0)
    quieter = _row(candidateId="quiet", waitMinutes=1.0, score=15.0, loaderId=11, roadIds=["R-2"])
    result = finalize_recommendations(
        [baseline, quieter],
        objectives=[ObjectiveProfile.BALANCE_LOADING_POINTS],
    )
    assert result["displayedCandidateIds"] == ["quiet"]


def test_reduce_cycle_delay_keeps_combined_score():
    baseline = _row(candidateId="now", isCurrent=True, distanceKm=5.0, waitMinutes=8.0, score=5.0)
    shorter_worse_score = _row(
        candidateId="near",
        distanceKm=1.0,
        waitMinutes=20.0,
        score=21.0,
        loaderId=11,
        roadIds=["R-2"],
    )
    result = finalize_recommendations(
        [baseline, shorter_worse_score],
        objectives=[ObjectiveProfile.REDUCE_CYCLE_DELAY],
    )
    assert classify_relation(shorter_worse_score, baseline, [ObjectiveProfile.REDUCE_CYCLE_DELAY]) == CandidateRelation.TRADEOFF
    assert result["displayedCandidateIds"] == []
    assert result["workflowStatus"] == "NO_CHANGE_RECOMMENDED"


def test_null_objective_metric_is_not_treated_as_zero_or_improvement():
    baseline = _row(candidateId="now", isCurrent=True, waitMinutes=6.0, score=10.0)
    unknown = _row(candidateId="gap", waitMinutes=None, score=None, loaderId=11, roadIds=["R-2"])
    result = finalize_recommendations(
        [baseline, unknown],
        objectives=[ObjectiveProfile.REDUCE_WAITING_TIME],
    )
    assert classify_relation(unknown, baseline, [ObjectiveProfile.REDUCE_WAITING_TIME]) == CandidateRelation.TRADEOFF
    assert result["displayedCandidateIds"] == []


def test_reviewer_may_order_tied_equivalents():
    baseline = _row(candidateId="now", isCurrent=True, waitMinutes=0.0, score=4.7, loaderId=10, roadIds=["R-1"])
    first = _row(candidateId="eq-a", waitMinutes=0.0, score=4.7, loaderId=11, roadIds=["R-2"])
    second = _row(candidateId="eq-b", waitMinutes=0.0, score=4.7, loaderId=12, roadIds=["R-3"])
    result = finalize_recommendations(
        [baseline, first, second],
        preferred_ids=["eq-b"],
        objectives=[ObjectiveProfile.REDUCE_WAITING_TIME],
    )
    assert result["displayedCandidateIds"][0] == "eq-b"
    assert set(result["displayedCandidateIds"]) == {"eq-a", "eq-b"}
    by_id = {row["candidateId"]: row for row in result["candidates"]}
    assert by_id["eq-b"]["candidateRelation"] == "EQUIVALENT"


def test_reviewer_cannot_replace_objectively_better_candidate():
    baseline = _row(candidateId="now", isCurrent=True, waitMinutes=9.0, score=14.0)
    better = _row(candidateId="best", waitMinutes=0.0, score=12.0, loaderId=11, roadIds=["R-2"])
    worse = _row(candidateId="worse", waitMinutes=4.0, score=8.0, loaderId=12, roadIds=["R-3"])
    result = finalize_recommendations(
        [baseline, worse, better],
        preferred_ids=["worse"],
        objectives=[ObjectiveProfile.REDUCE_WAITING_TIME],
    )
    assert result["displayedCandidateIds"][0] == "best"
    assert result["recommendedCandidateId"] == "best"


def test_invalid_preferred_id_is_ignored():
    baseline = _row(candidateId="now", isCurrent=True, waitMinutes=0.0, score=4.7)
    tied = _row(candidateId="eq", waitMinutes=0.0, score=4.7, loaderId=11, roadIds=["R-2"])
    result = finalize_recommendations(
        [baseline, tied],
        preferred_ids=["invented", "missing"],
        objectives=[ObjectiveProfile.REDUCE_WAITING_TIME],
    )
    assert result["displayedCandidateIds"] == ["eq"]


def test_caution_may_append_worse_candidate_but_not_as_first_when_better_exists():
    baseline = _row(candidateId="now", isCurrent=True, waitMinutes=9.0, score=14.0)
    better = _row(candidateId="best", waitMinutes=0.0, score=4.7, loaderId=11, roadIds=["R-2"])
    worse = _row(candidateId="worse", waitMinutes=12.0, score=20.0, loaderId=12, roadIds=["R-3"])
    result = finalize_recommendations(
        [baseline, better, worse],
        preferred_ids=["worse"],
        review_status=ReviewStatus.APPROVED_WITH_CAUTION,
        objectives=[ObjectiveProfile.REDUCE_WAITING_TIME],
    )
    assert result["displayedCandidateIds"][0] == "best"
    assert "worse" in result["displayedCandidateIds"]
