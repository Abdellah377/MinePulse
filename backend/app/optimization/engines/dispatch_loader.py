"""DISPATCH_LOADER engine: wrap generate_candidates. No weight tuning."""

from __future__ import annotations

from typing import Any

from app.optimization.solver import DEFAULT_WEIGHTS, generate_candidates

ENGINE_ID = "DISPATCH_LOADER"
ENGINE_VERSION = "1.0.0"


def execute(*, trusted: dict[str, Any], loaders: list[Any] | None = None) -> list[dict]:
    """Score loader×path candidates with the frozen default weights."""
    return generate_candidates(
        truck=trusted.get("truck"),
        assignment=trusted.get("assignment"),
        loaders=loaders if loaders is not None else trusted.get("loaders") or [],
        roads=trusted.get("roads") or [],
        zone_codes=trusted.get("zone_codes") or {},
        loading=trusted.get("loading") or {"loaders": []},
        origin_code=trusted.get("origin_code"),
        dest_code=trusted.get("dest_code"),
        weights=dict(DEFAULT_WEIGHTS),
        loader_zones=trusted.get("loader_zones") or {},
    )
