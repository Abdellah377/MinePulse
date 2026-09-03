"""Pending operator commitments stay distinct from measured wait."""

from app.optimization.pending import attach_pending_projection, pending_commitment_counts


def test_pending_fields_do_not_change_wait_minutes():
    candidates = [
        {"candidateId": "c-1", "loaderId": 11, "waitMinutes": 0.0, "score": 4.0},
        {"candidateId": "c-2", "loaderId": 10, "waitMinutes": 8.0, "score": 12.0},
    ]
    annotated = attach_pending_projection(
        candidates,
        pending_by_loader={11: 3, 10: 0},
        waiting_by_loader={11: 0, 10: 2},
    )
    assert annotated[0]["waitMinutes"] == 0.0
    assert annotated[1]["waitMinutes"] == 8.0
    assert annotated[0]["score"] == 4.0
    assert annotated[0]["pendingCommitmentCount"] == 3
    assert annotated[0]["projectedPressure"] == 3
    assert annotated[1]["pendingCommitmentCount"] == 0
    assert annotated[1]["projectedPressure"] == 2
    assert annotated[0]["projectedWaitMinutes"] is None


def test_projected_wait_only_when_service_model_known():
    rows = attach_pending_projection(
        [{"candidateId": "c-1", "loaderId": 11, "waitMinutes": 0.0}],
        pending_by_loader={11: 2},
        waiting_by_loader={11: 0},
        service_minutes=3.0,
    )
    assert rows[0]["waitMinutes"] == 0.0
    assert rows[0]["projectedWaitMinutes"] == 6.0


def test_pending_commitment_counts_open_accepted_only():
    counts = pending_commitment_counts(
        [
            {"decisionType": "ACCEPTED", "followUpStatus": "OPEN", "loaderId": 11},
            {"decisionType": "ACCEPTED", "followUpStatus": "OPEN", "loaderId": 11},
            {"decisionType": "REJECTED", "followUpStatus": "OPEN", "loaderId": 11},
            {"decisionType": "ACCEPTED", "followUpStatus": "RESOLVED", "loaderId": 11},
            {"decisionType": "MODIFIED", "followUpStatus": "OPEN", "loaderId": 10},
            {"decisionType": "ACCEPTED", "followUpStatus": "OPEN", "loaderId": None},
        ]
    )
    assert counts == {11: 2, 10: 1}
