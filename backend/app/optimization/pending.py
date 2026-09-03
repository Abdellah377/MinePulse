"""Pending operator commitments. Measured wait stays measured."""

from __future__ import annotations

from collections import Counter
from typing import Any

PENDING_DECISION_TYPES = frozenset({"ACCEPTED", "MODIFIED"})
PENDING_FOLLOW_UP = frozenset({"OPEN"})


def loader_id_from_payload(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("loaderId", "loader_id", "targetLoaderId"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    for nested_key in ("recommendedCandidate", "candidate", "operator_action", "operatorAction"):
        nested = loader_id_from_payload(payload.get(nested_key))
        if nested is not None:
            return nested
    return None


def pending_commitment_counts(rows: list[dict[str, Any]]) -> dict[int, int]:
    counts: Counter[int] = Counter()
    for row in rows:
        decision = str(row.get("decisionType") or row.get("decision_type") or "")
        follow = str(row.get("followUpStatus") or row.get("follow_up_status") or "OPEN")
        if decision not in PENDING_DECISION_TYPES or follow not in PENDING_FOLLOW_UP:
            continue
        loader_id = row.get("loaderId")
        if loader_id is None:
            loader_id = loader_id_from_payload(row.get("originalRecommendation") or row.get("original_recommendation"))
        if loader_id is None:
            continue
        try:
            counts[int(loader_id)] += 1
        except (TypeError, ValueError):
            continue
    return dict(counts)


def attach_pending_projection(
    candidates: list[dict[str, Any]],
    pending_by_loader: dict[int, int],
    *,
    waiting_by_loader: dict[int, int] | None = None,
    service_minutes: float | None = None,
) -> list[dict[str, Any]]:
    waiting = waiting_by_loader or {}
    annotated: list[dict[str, Any]] = []
    for row in candidates:
        item = dict(row)
        measured = item.get("waitMinutes")
        loader_id = item.get("loaderId")
        try:
            pending = int(pending_by_loader.get(int(loader_id), 0) or 0) if loader_id is not None else 0
        except (TypeError, ValueError):
            pending = 0
        queued = waiting.get(loader_id) if loader_id is not None else None
        item["pendingCommitmentCount"] = pending
        if queued is None:
            item["projectedPressure"] = pending
        else:
            item["projectedPressure"] = int(queued) + pending
        if measured is not None and service_minutes is not None and pending > 0:
            item["projectedWaitMinutes"] = round(float(measured) + pending * float(service_minutes), 3)
        else:
            item["projectedWaitMinutes"] = None
        item["waitMinutes"] = measured
        annotated.append(item)
    return annotated
