"""Read-only haul-road catalog. AI and routing evidence may import this module.

Mutations stay in ``app.services.operational.roads`` and must not be imported here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.db.models import HaulRoad, Zone
from app.services.operational.assignments import current_assignment
from app.services.operational.context import OperationalContext
from app.services.operational.equipment import latest_positions


def catalog_row(road: HaulRoad, zone_by_id: dict[int, Zone]) -> dict:
    from_zone = zone_by_id.get(road.from_zone_id) if road.from_zone_id is not None else None
    to_zone = zone_by_id.get(road.to_zone_id) if road.to_zone_id is not None else None
    return {
        "id": road.code,
        "name": road.name or None,
        "fromZoneId": from_zone.code if from_zone else None,
        "toZoneId": to_zone.code if to_zone else None,
        "status": getattr(road, "status", None),
        "distanceKm": road.distance_km,
        "speedLimitKmh": getattr(road, "speed_limit_kmh", None),
        "description": getattr(road, "description", None),
        "statusReason": getattr(road, "status_reason", None),
        "statusNote": getattr(road, "status_note", None),
    }


def zone_brief(zone: Zone) -> dict:
    zone_type = zone.type.value if hasattr(zone.type, "value") else zone.type
    return {
        "zoneId": zone.zone_id,
        "code": zone.code,
        "name": zone.name,
        "type": zone_type,
        "description": zone.description,
    }


def list_road_catalog(session: Session, ctx: OperationalContext) -> tuple[list[dict], dict[int, Zone]]:
    zones = list(
        session.scalars(select(Zone).where(Zone.site_id == ctx.site_id).options(defer(Zone.geometry)))
    )
    zone_by_id = {zone.zone_id: zone for zone in zones}
    roads = list(
        session.scalars(
            select(HaulRoad).where(HaulRoad.site_id == ctx.site_id).options(defer(HaulRoad.geometry))
        )
    )
    return [catalog_row(road, zone_by_id) for road in roads], zone_by_id


def resolve_haul_endpoints(
    session: Session,
    ctx: OperationalContext,
    zone_by_id: dict[int, Zone],
    *,
    equipment_id: int | None = None,
    zone_id: int | None = None,
    parameters: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """Resolve origin/destination from operator request, assignment, then position."""
    origin: str | None = None
    destination: str | None = None
    params = [item for item in (parameters or []) if item]
    if len(params) >= 1:
        origin = params[0]
    if len(params) >= 2:
        destination = params[1]
    codes = {zone.zone_id: zone.code for zone in zone_by_id.values()}
    if equipment_id is not None:
        assignment = current_assignment(session, equipment_id, ctx)
        if assignment is not None:
            if assignment.origin_zone_id is not None:
                origin = origin or codes.get(assignment.origin_zone_id)
            if assignment.destination_zone_id is not None:
                destination = destination or codes.get(assignment.destination_zone_id)
        position = latest_positions(session, ctx.site_id).get(equipment_id)
        if position is not None and position.zone_id is not None:
            origin = origin or codes.get(position.zone_id)
    if zone_id is not None:
        origin = origin or codes.get(zone_id)
    return origin, destination
