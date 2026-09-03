"""Authoritative loader geography. Never infers a bench from the subject truck."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LOCATION_POSITION = "position"
LOCATION_HOME = "home_zone"
LOCATION_UNKNOWN = "unknown"
DEFAULT_ZONE_CAPACITY = 3


def zone_runtime_capacity(capacity: int | None) -> int:
    """Treat missing capacity as the default occupancy; keep an explicit zero."""
    if capacity is None:
        return DEFAULT_ZONE_CAPACITY
    return int(capacity)


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def is_fresh_position(position_ts: datetime | None, now: datetime, stale_seconds: float) -> bool:
    observed = _aware(position_ts)
    clock = _aware(now)
    if observed is None or clock is None:
        return False
    age = (clock - observed).total_seconds()
    return 0.0 <= age <= float(stale_seconds)


def resolve_loader_location(
    *,
    position_zone_id: int | None,
    position_ts: datetime | None,
    home_zone_id: int | None,
    now: datetime,
    stale_seconds: float,
    zone_codes: dict[int, str],
) -> tuple[str | None, str]:
    """Fresh EquipmentPosition.zone_id, else home_zone_id, else UNKNOWN."""
    if position_zone_id is not None and is_fresh_position(position_ts, now, stale_seconds):
        code = zone_codes.get(position_zone_id)
        if code:
            return code, LOCATION_POSITION
    if home_zone_id is not None:
        code = zone_codes.get(home_zone_id)
        if code:
            return code, LOCATION_HOME
    return None, LOCATION_UNKNOWN


def collect_loader_locations(
    *,
    loaders: list[Any],
    positions: dict[int, Any],
    zone_codes: dict[int, str],
    now: datetime,
    stale_seconds: float,
) -> tuple[dict[int, str], dict[int, str]]:
    zones: dict[int, str] = {}
    sources: dict[int, str] = {}
    for loader in loaders:
        loader_id = getattr(loader, "equipment_id", None)
        if loader_id is None:
            continue
        position = positions.get(loader_id)
        code, source = resolve_loader_location(
            position_zone_id=getattr(position, "zone_id", None) if position is not None else None,
            position_ts=getattr(position, "ts", None) if position is not None else None,
            home_zone_id=getattr(loader, "home_zone_id", None),
            now=now,
            stale_seconds=stale_seconds,
            zone_codes=zone_codes,
        )
        sources[loader_id] = source
        if code:
            zones[loader_id] = code
    return zones, sources
