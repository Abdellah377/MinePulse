from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import Ctx, DbSession
from app.db.models import Alert, Equipment, Zone
from app.mappers.dto import alert_to_dto, road_to_dto, zone_to_dto
from app.schemas.roads import RoadCreateRequest, RoadPatchRequest
from app.schemas.zones import ZoneCreateRequest, ZonePatchRequest
from app.services.operational import roads as road_service
from app.services.operational import zones as zone_service
from app.services.operational.alerts import alert_operational_time_expression

router = APIRouter()
roads_router = APIRouter()
events_router = APIRouter()


@router.get("")
def list_zones(session: DbSession, ctx: Ctx):
    zones = zone_service.list_zones(session, ctx)
    return [zone_to_dto(z, ctx.site_code) for z in zones]


@router.post("")
def create_zone(body: ZoneCreateRequest, session: DbSession, ctx: Ctx):
    zone = zone_service.create_zone(
        session,
        ctx,
        code=body.code,
        name=body.name,
        zone_type=body.type,
        points=[p.model_dump() for p in body.points],
        color=body.color,
        description=body.description,
        capacity=body.capacity,
    )
    return zone_to_dto(zone, ctx.site_code)


@router.patch("/{code}")
def patch_zone(
    code: str,
    body: ZonePatchRequest,
    session: DbSession,
    ctx: Ctx,
):
    zone = zone_service.update_zone(
        session,
        ctx,
        code,
        name=body.name,
        zone_type=body.type,
        points=[p.model_dump() for p in body.points] if body.points else None,
        color=body.color,
        description=body.description,
        capacity=body.capacity,
    )
    return zone_to_dto(zone, ctx.site_code)


@router.delete("/{code}")
def delete_zone(code: str, session: DbSession, ctx: Ctx):
    zone_service.delete_zone(session, ctx, code)
    return {"ok": True}


@roads_router.get("")
def list_roads(session: DbSession, ctx: Ctx):
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    zone_codes = {z.zone_id: z.code for z in zones}
    return [road_to_dto(r, zone_codes, ctx.site_code) for r in road_service.list_roads(session, ctx)]


@roads_router.post("")
def create_road(body: RoadCreateRequest, session: DbSession, ctx: Ctx):
    road = road_service.create_road(
        session,
        ctx,
        code=body.code,
        name=body.name,
        points=[p.model_dump() for p in body.points],
        from_zone_id=body.fromZoneId,
        to_zone_id=body.toZoneId,
        distance_km=body.distanceKm,
        speed_limit_kmh=body.speedLimitKmh,
        description=body.description,
        status=body.status,
        status_reason=body.statusReason,
        status_note=body.statusNote,
    )
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    zone_codes = {z.zone_id: z.code for z in zones}
    return road_to_dto(road, zone_codes, ctx.site_code)


@roads_router.patch("/{code}")
def patch_road(code: str, body: RoadPatchRequest, session: DbSession, ctx: Ctx):
    road = road_service.update_road(
        session,
        ctx,
        code,
        name=body.name,
        from_zone_id=body.fromZoneId,
        to_zone_id=body.toZoneId,
        points=[p.model_dump() for p in body.points] if body.points else None,
        distance_km=body.distanceKm,
        speed_limit_kmh=body.speedLimitKmh,
        description=body.description,
        status=body.status,
        status_reason=body.statusReason,
        status_note=body.statusNote,
    )
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    zone_codes = {z.zone_id: z.code for z in zones}
    return road_to_dto(road, zone_codes, ctx.site_code)


@roads_router.delete("/{code}")
def delete_road(code: str, session: DbSession, ctx: Ctx):
    road_service.delete_road(session, ctx, code)
    return {"ok": True}


@events_router.get("/events")
def list_events(session: DbSession):
    from app.db.models import SystemEvent

    rows = session.scalars(select(SystemEvent).order_by(SystemEvent.ts.desc()).limit(100)).all()
    return [
        {
            "id": str(r.system_event_id),
            "ts": r.ts.isoformat(),
            "type": r.event_type,
            "message": r.message,
            "equipmentId": r.equipment_id,
        }
        for r in rows
    ]


@events_router.get("/alerts")
def list_alerts(session: DbSession, ctx: Ctx):
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    equipment = session.scalars(select(Equipment).where(Equipment.site_id == ctx.site_id)).all()
    zone_codes = {z.zone_id: z.code for z in zones}
    equip_codes = {e.equipment_id: e.code for e in equipment}
    alerts = session.scalars(
        select(Alert).order_by(alert_operational_time_expression().desc()).limit(100)
    ).all()
    return [alert_to_dto(a, equip_codes, zone_codes, session=session) for a in alerts]
