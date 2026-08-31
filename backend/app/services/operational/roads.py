"""Haul-road catalog mutations. Operator-only — never called from AI or monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from math import atan2, cos, radians, sin, sqrt

from fastapi import HTTPException
from geoalchemy2 import WKTElement
from shapely.geometry import LineString
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HaulRoad, Zone
from app.mappers.geo import workspace_to_lng_lat
from app.services.operational.context import OperationalContext

ROAD_STATUSES = frozenset({"OPEN", "CLOSED", "RESTRICTED"})
STATUS_REASONS = frozenset(
    {"BLASTING", "MAINTENANCE", "ROAD_DAMAGE", "FLOODING", "CONGESTION_CONTROL", "OTHER"}
)


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _points_to_line(points: list[dict]) -> tuple[WKTElement, float]:
    if len(points) < 2:
        raise HTTPException(status_code=400, detail="Road requires at least 2 points")
    coords = [workspace_to_lng_lat(float(p["x"]), float(p["y"])) for p in points]
    line = LineString(coords)
    distance = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(coords, coords[1:]):
        distance += _haversine_km(lng1, lat1, lng2, lat2)
    return WKTElement(line.wkt, srid=4326), round(distance, 3)


def _zone_id(session: Session, ctx: OperationalContext, code: str | None) -> int | None:
    if not code:
        return None
    zone = session.scalar(
        select(Zone).where(Zone.site_id == ctx.site_id, Zone.code == code, Zone.status == "ACTIVE")
    )
    if not zone:
        raise HTTPException(status_code=400, detail=f"Unknown zone: {code}")
    return zone.zone_id


def _validate_status(status: str | None) -> str:
    value = (status or "OPEN").upper()
    if value not in ROAD_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid road status")
    return value


def _validate_reason(status: str, reason: str | None) -> str | None:
    if status == "OPEN":
        return None
    if reason is None or reason == "":
        return None
    value = reason.upper()
    if value not in STATUS_REASONS:
        raise HTTPException(status_code=400, detail="Invalid road status reason")
    return value


def list_roads(session: Session, ctx: OperationalContext) -> list[HaulRoad]:
    return list(session.scalars(select(HaulRoad).where(HaulRoad.site_id == ctx.site_id)))


def get_road(session: Session, ctx: OperationalContext, code: str) -> HaulRoad:
    road = session.scalar(select(HaulRoad).where(HaulRoad.site_id == ctx.site_id, HaulRoad.code == code))
    if not road:
        raise HTTPException(status_code=404, detail="Road not found")
    return road


def create_road(
    session: Session,
    ctx: OperationalContext,
    *,
    code: str,
    name: str,
    points: list[dict],
    from_zone_id: str | None = None,
    to_zone_id: str | None = None,
    distance_km: float | None = None,
    speed_limit_kmh: float | None = None,
    description: str | None = None,
    status: str | None = "OPEN",
    status_reason: str | None = None,
    status_note: str | None = None,
) -> HaulRoad:
    existing = session.scalar(select(HaulRoad).where(HaulRoad.site_id == ctx.site_id, HaulRoad.code == code))
    if existing:
        raise HTTPException(status_code=409, detail=f"Road code exists: {code}")
    geometry, computed = _points_to_line(points)
    resolved_status = _validate_status(status)
    road = HaulRoad(
        site_id=ctx.site_id,
        code=code,
        name=name,
        from_zone_id=_zone_id(session, ctx, from_zone_id),
        to_zone_id=_zone_id(session, ctx, to_zone_id),
        distance_km=Decimal(str(distance_km if distance_km is not None else computed)),
        speed_limit_kmh=Decimal(str(speed_limit_kmh)) if speed_limit_kmh is not None else None,
        status=resolved_status,
        description=description,
        status_reason=_validate_reason(resolved_status, status_reason),
        status_note=None if resolved_status == "OPEN" else status_note,
        status_changed_at=datetime.now(timezone.utc) if resolved_status != "OPEN" else None,
        geometry=geometry,
        metadata_={},
    )
    session.add(road)
    session.commit()
    session.refresh(road)
    return road


def update_road(
    session: Session,
    ctx: OperationalContext,
    code: str,
    *,
    name: str | None = None,
    from_zone_id: str | None = None,
    to_zone_id: str | None = None,
    points: list[dict] | None = None,
    distance_km: float | None = None,
    speed_limit_kmh: float | None = None,
    description: str | None = None,
    status: str | None = None,
    status_reason: str | None = None,
    status_note: str | None = None,
) -> HaulRoad:
    road = get_road(session, ctx, code)
    if name is not None:
        road.name = name
    if from_zone_id is not None:
        road.from_zone_id = _zone_id(session, ctx, from_zone_id or None)
    if to_zone_id is not None:
        road.to_zone_id = _zone_id(session, ctx, to_zone_id or None)
    if points is not None:
        geometry, computed = _points_to_line(points)
        road.geometry = geometry
        if distance_km is None:
            road.distance_km = Decimal(str(computed))
    if distance_km is not None:
        road.distance_km = Decimal(str(distance_km))
    if speed_limit_kmh is not None:
        road.speed_limit_kmh = Decimal(str(speed_limit_kmh))
    if description is not None:
        road.description = description
    if status is not None:
        resolved = _validate_status(status)
        road.status = resolved
        road.status_changed_at = datetime.now(timezone.utc)
        if resolved == "OPEN":
            road.status_reason = None
            road.status_note = None
        else:
            if status_reason is not None:
                road.status_reason = _validate_reason(resolved, status_reason)
            if status_note is not None:
                road.status_note = status_note
    elif status_reason is not None or status_note is not None:
        if road.status == "OPEN":
            raise HTTPException(status_code=400, detail="Status reason requires CLOSED or RESTRICTED")
        if status_reason is not None:
            road.status_reason = _validate_reason(road.status, status_reason)
        if status_note is not None:
            road.status_note = status_note
    session.commit()
    session.refresh(road)
    return road


def delete_road(session: Session, ctx: OperationalContext, code: str) -> None:
    road = get_road(session, ctx, code)
    session.delete(road)
    session.commit()
