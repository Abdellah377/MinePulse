"""Audit accepted recommendations against hard operational constraints.

No LLM. No simulator import. Unknown loader geography must never be filled
from the subject truck haul origin.
"""

from __future__ import annotations

from typing import Any


def recommendation_constraint_violations(
    candidates: list[dict[str, Any]],
    *,
    loader_zones: dict[int, str],
    origin_code: str | None,
    hard_exclude_loader_ids: set[int] | None = None,
    measured_wait: dict[int, float | None] | None = None,
    closed_road_ids: set[str] | None = None,
    unavailable_loader_ids: set[int] | None = None,
) -> list[str]:
    """Return human-readable violations. Empty means the rec set is constraint-clean."""
    excluded = hard_exclude_loader_ids or set()
    unavailable = unavailable_loader_ids or set()
    closed = {str(item) for item in (closed_road_ids or set())}
    waits = measured_wait or {}
    violations: list[str] = []
    for row in candidates:
        loader_id = row.get("loaderId")
        candidate_id = row.get("candidateId") or "?"
        origin = row.get("originZoneCode")
        if loader_id is None:
            violations.append(f"{candidate_id}: missing loaderId")
            continue
        try:
            loader_id = int(loader_id)
        except (TypeError, ValueError):
            violations.append(f"{candidate_id}: non-integer loaderId")
            continue
        known = loader_zones.get(loader_id)
        if loader_id in excluded:
            violations.append(f"{candidate_id}: hard-excluded loader {loader_id}")
        if loader_id in unavailable:
            violations.append(f"{candidate_id}: unavailable loader {loader_id}")
        if known is None:
            violations.append(f"{candidate_id}: unknown loader location used as origin={origin}")
        elif origin != known:
            violations.append(f"{candidate_id}: origin {origin} != authoritative {known}")
        if known is None and origin_code is not None and origin == origin_code:
            violations.append(f"{candidate_id}: truck origin used as unknown-loader bench")
        if loader_id in waits and row.get("waitMinutes") != waits[loader_id]:
            violations.append(
                f"{candidate_id}: waitMinutes {row.get('waitMinutes')} mutated from measured {waits[loader_id]}"
            )
        for road_id in row.get("roadIds") or []:
            if str(road_id) in closed:
                violations.append(f"{candidate_id}: closed road {road_id}")
    return violations
