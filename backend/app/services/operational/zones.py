"""Zone CRUD against PostGIS."""

from __future__ import annotations

from fastapi import HTTPException
from geoalchemy2 import WKTElement
from shapely.geometry import Polygon
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ZoneType
from app.db.models import Zone
from app.mappers.geo import workspace_to_lng_lat
from app.services.operational.context import OperationalContext

_UI_TO_ZONE_TYPE = {
    "chargement": ZoneType.LOADING_BENCH,
    "dechargement": ZoneType.DUMP_AREA,
    "concasseur": ZoneType.CRUSHER,
    "fuel": ZoneType.FUEL_STATION,
    "atelier": ZoneType.MAINTENANCE_WORKSHOP,
    "parking": ZoneType.PARKING,
    "restreinte": ZoneType.RESTRICTED_AREA,
}


def _points_to_polygon(points: list[dict]) -> WKTElement:
    if len(points) < 3:
        raise HTTPException(status_code=400, detail="Zone requires at least 3 points")
    ring = [workspace_to_lng_lat(float(p["x"]), float(p["y"])) for p in points]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    poly = Polygon(ring)
    return WKTElement(poly.wkt, srid=4326)


def list_zones(session: Session, ctx: OperationalContext) -> list[Zone]:
    return list(
        session.scalars(select(Zone).where(Zone.site_id == ctx.site_id, Zone.status == "ACTIVE"))
    )


def create_zone(
    session: Session,
    ctx: OperationalContext,
    *,
    code: str,
    name: str,
    zone_type: str,
    points: list[dict],
    color: str | None = None,
    description: str | None = None,
    capacity: int | None = None,
) -> Zone:
    existing = session.scalar(
        select(Zone).where(Zone.site_id == ctx.site_id, Zone.code == code)
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Zone code exists: {code}")
    zt = _UI_TO_ZONE_TYPE.get(zone_type, ZoneType.RESTRICTED_AREA)
    meta: dict = {}
    if color:
        meta["color"] = color
    zone = Zone(
        site_id=ctx.site_id,
        code=code,
        name=name,
        type=zt,
        description=description or "",
        capacity=capacity or 0,
        status="ACTIVE",
        geometry=_points_to_polygon(points),
        metadata_=meta,
    )
    session.add(zone)
    session.commit()
    session.refresh(zone)
    return zone


def update_zone(
    session: Session,
    ctx: OperationalContext,
    code: str,
    *,
    name: str | None = None,
    zone_type: str | None = None,
    points: list[dict] | None = None,
    color: str | None = None,
    description: str | None = None,
    capacity: int | None = None,
) -> Zone:
    zone = session.scalar(select(Zone).where(Zone.site_id == ctx.site_id, Zone.code == code))
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    if name is not None:
        zone.name = name
    if zone_type is not None:
        zone.type = _UI_TO_ZONE_TYPE.get(zone_type, zone.type)
    if description is not None:
        zone.description = description
    if capacity is not None:
        zone.capacity = capacity
    if points is not None:
        zone.geometry = _points_to_polygon(points)
    if color is not None:
        meta = dict(zone.metadata_ or {})
        meta["color"] = color
        zone.metadata_ = meta
    session.commit()
    session.refresh(zone)
    return zone


def delete_zone(session: Session, ctx: OperationalContext, code: str) -> None:
    zone = session.scalar(select(Zone).where(Zone.site_id == ctx.site_id, Zone.code == code))
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    zone.status = "INACTIVE"
    session.commit()
