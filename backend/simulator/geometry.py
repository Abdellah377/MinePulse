"""Load and use PostGIS zone/road geometries as the spatial source of truth."""

from __future__ import annotations

import math
from dataclasses import dataclass

from geoalchemy2 import WKTElement
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString, Point, Polygon
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import HaulRoad, Zone


@dataclass
class ZoneGeom:
    zone_id: int
    code: str
    polygon: Polygon
    centroid: tuple[float, float]  # lng, lat


@dataclass
class RoadGeom:
    road_id: int
    code: str
    from_zone_code: str
    to_zone_code: str
    distance_km: float
    speed_limit_kmh: float
    grade_pct: float
    quality_score: float
    line: LineString  # coords as (lng, lat)


def load_zones(session: Session, site_id: int) -> dict[str, ZoneGeom]:
    zones = session.scalars(select(Zone).where(Zone.site_id == site_id).order_by(Zone.code)).all()
    out: dict[str, ZoneGeom] = {}
    for z in zones:
        poly: Polygon = to_shape(z.geometry)
        c = poly.centroid
        out[z.code] = ZoneGeom(
            zone_id=z.zone_id,
            code=z.code,
            polygon=poly,
            centroid=(float(c.x), float(c.y)),
        )
    return out


def load_roads(
    session: Session, site_id: int, zone_id_to_code: dict[int, str]
) -> dict[str, RoadGeom]:
    roads = session.scalars(
        select(HaulRoad).where(HaulRoad.site_id == site_id).order_by(HaulRoad.code)
    ).all()
    out: dict[str, RoadGeom] = {}
    for r in roads:
        line: LineString = to_shape(r.geometry)
        from_code = zone_id_to_code.get(r.from_zone_id or 0, "")
        to_code = zone_id_to_code.get(r.to_zone_id or 0, "")
        dist = float(r.distance_km) if r.distance_km is not None else _line_length_km(line)
        geom = RoadGeom(
            road_id=r.road_id,
            code=r.code,
            from_zone_code=from_code,
            to_zone_code=to_code,
            distance_km=dist,
            speed_limit_kmh=float(r.speed_limit_kmh or 40),
            grade_pct=float(r.road_grade_pct) if r.road_grade_pct is not None else 0.0,
            quality_score=float(r.road_quality) if r.road_quality is not None else 85.0,
            line=line,
        )
        out[r.code] = geom
        out[f"{from_code}->{to_code}"] = geom
    return out


def find_road(
    roads: dict[str, RoadGeom], from_code: str, to_code: str
) -> tuple[RoadGeom | None, bool]:
    """Return (road, need_reverse)."""
    key = f"{from_code}->{to_code}"
    if key in roads:
        return roads[key], False
    rev = f"{to_code}->{from_code}"
    if rev in roads:
        return roads[rev], True
    return None, False


def _line_length_km(line: LineString) -> float:
    coords = list(line.coords)
    total = 0.0
    for i in range(len(coords) - 1):
        total += _haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
    return round(total, 3) or 0.1


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def interpolate_linestring(
    line: LineString, t: float, *, reverse: bool = False
) -> tuple[float, float, float]:
    """Return (lng, lat, heading_deg) at fraction t along line."""
    t = max(0.0, min(1.0, t))
    coords = list(line.coords)
    if reverse:
        coords = list(reversed(coords))
    if len(coords) < 2:
        c = coords[0] if coords else (0.0, 0.0)
        return float(c[0]), float(c[1]), 0.0

    segs: list[float] = []
    total = 0.0
    for i in range(len(coords) - 1):
        d = math.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1])
        segs.append(d)
        total += d
    if total <= 0:
        return float(coords[0][0]), float(coords[0][1]), 0.0

    target = t * total
    acc = 0.0
    for i, d in enumerate(segs):
        if acc + d >= target or i == len(segs) - 1:
            local = 0.0 if d <= 0 else (target - acc) / d
            local = max(0.0, min(1.0, local))
            lng1, lat1 = coords[i]
            lng2, lat2 = coords[i + 1]
            lng = lng1 + (lng2 - lng1) * local
            lat = lat1 + (lat2 - lat1) * local
            heading = math.degrees(math.atan2(lng2 - lng1, lat2 - lat1)) % 360
            return float(lng), float(lat), heading
        acc += d
    c = coords[-1]
    return float(c[0]), float(c[1]), 0.0


def point_wkt(lng: float, lat: float) -> WKTElement:
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def resolve_zone_id_from_geom(
    zones: dict[str, ZoneGeom],
    lng: float,
    lat: float,
    *,
    moving: bool,
) -> int | None:
    """In-memory ST_Contains equivalent using already-loaded shapely polygons."""
    if moving:
        return None
    pt = Point(lng, lat)
    for zg in zones.values():
        if zg.polygon.contains(pt):
            return zg.zone_id
    return None


def resolve_zone_id(
    session: Session | None,
    site_id: int,
    lng: float,
    lat: float,
    *,
    moving: bool,
    zones: dict[str, ZoneGeom] | None = None,
) -> int | None:
    """Spatial zone lookup. Travelling trucks get NULL."""
    if moving:
        return None
    if zones is not None:
        return resolve_zone_id_from_geom(zones, lng, lat, moving=False)
    if session is None:
        raise ValueError("session is required when in-memory zones are not provided")
    row = session.execute(
        text(
            """
            SELECT zone_id FROM zones
            WHERE site_id = :site_id
              AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
            LIMIT 1
            """
        ),
        {"site_id": site_id, "lng": lng, "lat": lat},
    ).first()
    return int(row[0]) if row else None
