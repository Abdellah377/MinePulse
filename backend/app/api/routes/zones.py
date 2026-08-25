from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import Ctx, DbSession
from app.db.models import Alert, Equipment, HaulRoad, Zone
from app.mappers.dto import alert_to_dto, road_to_dto, zone_to_dto
from app.schemas.zones import ZoneCreateRequest, ZonePatchRequest
from app.services.operational import zones as zone_service

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
    roads = session.scalars(select(HaulRoad).where(HaulRoad.site_id == ctx.site_id)).all()
    return [road_to_dto(r, zone_codes, ctx.site_code) for r in roads]


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
    alerts = session.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(100)).all()
    return [alert_to_dto(a, equip_codes, zone_codes, session=session) for a in alerts]
