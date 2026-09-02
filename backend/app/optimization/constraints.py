"""Allowlisted constraint applicators. LLM may request codes; code applies them."""

from __future__ import annotations

from typing import Any

from app.optimization.contracts import ConstraintCode
from app.optimization.solver import UNAVAILABLE_STATES, _is_available


def apply_loader_constraints(
    loaders: list[Any],
    *,
    constraints: list[ConstraintCode],
    mechanical_risk_loader_ids: set[int],
) -> list[Any]:
    codes = set(constraints)
    rows = list(loaders)
    if ConstraintCode.EXCLUDE_UNAVAILABLE_EQUIPMENT in codes:
        rows = [row for row in rows if _is_available(row)]
    if ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK in codes and mechanical_risk_loader_ids:
        rows = [row for row in rows if getattr(row, "equipment_id", None) not in mechanical_risk_loader_ids]
    return rows


def apply_path_constraints(candidates: list[dict], constraints: list[ConstraintCode]) -> list[dict]:
    codes = set(constraints)
    rows = list(candidates)
    if ConstraintCode.AVOID_RESTRICTED_ROADS_WHEN_ALTERNATIVE_EXISTS in codes:
        rows = _drop_restricted_when_alternative_exists(rows)
    return rows


def _drop_restricted_when_alternative_exists(candidates: list[dict]) -> list[dict]:
    by_loader: dict[int | None, list[dict]] = {}
    for row in candidates:
        by_loader.setdefault(row.get("loaderId"), []).append(row)
    kept: list[dict] = []
    for group in by_loader.values():
        unrestricted = [row for row in group if "RESTRICTED" not in (row.get("constraintNotes") or [])]
        if unrestricted:
            kept.extend(unrestricted)
        else:
            kept.extend(group)
    order = {row.get("candidateId"): index for index, row in enumerate(candidates)}
    kept.sort(key=lambda row: order.get(row.get("candidateId"), 10_000))
    return kept


def unavailable_states():
    return UNAVAILABLE_STATES
