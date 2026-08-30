from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import Ctx, DbSession
from app.db.models import Equipment, Zone
from app.mappers.dto import enriched_equipment_dto, maintenance_history_for_equipment
from app.services.operational.equipment import build_fleet_bulk_context, list_site_equipment
from app.services.operational.failure_risk import current_failure_risk, failure_risk_to_dto

router = APIRouter()


@router.get("")
def list_equipment(session: DbSession, ctx: Ctx):
    equipment = list_site_equipment(session, ctx)
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    zone_codes = {z.zone_id: z.code for z in zones}
    bulk = build_fleet_bulk_context(session, list(equipment), ctx)
    return [
        enriched_equipment_dto(
            session,
            e,
            bulk.positions.get(e.equipment_id),
            bulk.telemetry.get(e.equipment_id),
            zone_codes,
            bulk.trips,
            site_code=ctx.site_code,
            ctx=ctx,
            bulk=bulk,
        )
        for e in equipment
    ]


@router.get("/live")
def live_equipment(session: DbSession, ctx: Ctx):
    return list_equipment(session, ctx)


@router.get("/{code}/detail")
def equipment_detail(code: str, session: DbSession, ctx: Ctx):
    eq = session.scalar(
        select(Equipment).where(Equipment.site_id == ctx.site_id, Equipment.code == code)
    )
    if not eq:
        raise HTTPException(status_code=404, detail="Equipment not found")
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    zone_codes = {z.zone_id: z.code for z in zones}
    bulk = build_fleet_bulk_context(session, [eq], ctx)
    return {
        "equipment": enriched_equipment_dto(
            session,
            eq,
            bulk.positions.get(eq.equipment_id),
            bulk.telemetry.get(eq.equipment_id),
            zone_codes,
            bulk.trips,
            site_code=ctx.site_code,
            ctx=ctx,
            bulk=bulk,
        ),
        "maintenanceHistory": maintenance_history_for_equipment(session, eq.equipment_id),
        "failureRisk": failure_risk_to_dto(current_failure_risk(session, eq, ctx.sim_now)),
    }
