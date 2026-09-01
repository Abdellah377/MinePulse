from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import Ctx, DbSession
from app.db.models import Zone
from app.services.operational.context import analysis_window
from app.services.operational.equipment import list_site_equipment
from app.services.operational.timeline import timeline_for_window

router = APIRouter()


@router.get("/timeline")
def timeline(
    session: DbSession,
    ctx: Ctx,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    poste: str | None = Query(None),
):
    equipment = list_site_equipment(session, ctx)
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    equip_codes = {e.equipment_id: e.code for e in equipment}
    zone_names = {z.zone_id: z.name for z in zones}
    since, until = analysis_window(session, ctx, from_date, to_date, poste)
    return timeline_for_window(session, ctx, since, until, equip_codes, zone_names)
