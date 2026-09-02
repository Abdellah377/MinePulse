"""ROUTE engine: current loader only, reuse candidate_paths via generate_candidates."""

from __future__ import annotations

from typing import Any

from app.optimization.engines.dispatch_loader import execute as execute_dispatch

ENGINE_ID = "ROUTE"
ENGINE_VERSION = "1.0.0"


def execute(*, trusted: dict[str, Any], loaders: list[Any] | None = None) -> list[dict]:
    assignment = trusted.get("assignment")
    current_id = getattr(assignment, "loader_id", None) if assignment is not None else None
    available = loaders if loaders is not None else trusted.get("loaders") or []
    if current_id is None:
        scoped = []
    else:
        scoped = [row for row in available if getattr(row, "equipment_id", None) == current_id]
    return execute_dispatch(trusted=trusted, loaders=scoped)
