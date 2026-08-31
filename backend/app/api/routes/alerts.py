from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.mappers.dto import alert_to_dto
from app.schemas.alerts import AlertPatchRequest
from app.services.operational.alerts import count_active_alerts, update_alert
from sqlalchemy import select
from app.db.models import Equipment, Zone

router = APIRouter()


def _alert_code_maps(session, ctx: Ctx) -> tuple[dict[int, str], dict[int, str]]:
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    equipment = session.scalars(select(Equipment).where(Equipment.site_id == ctx.site_id)).all()
    return (
        {e.equipment_id: e.code for e in equipment},
        {z.zone_id: z.code for z in zones},
    )


@router.get("/active-count")
def active_alert_count(session: DbSession, ctx: Ctx):
    return {"activeCount": count_active_alerts(session, ctx.site_id)}


@router.patch("/{alert_id}")
def patch_alert(alert_id: str, body: AlertPatchRequest, session: DbSession, ctx: Ctx):
    alert = update_alert(
        session,
        alert_id,
        site_id=ctx.site_id,
        status=body.status,
        assigned_to_operator_id=body.assigned_to_operator_id,
        actor_label=body.actor_label,
        resolution=body.resolution,
    )
    equip_codes, zone_codes = _alert_code_maps(session, ctx)
    return alert_to_dto(alert, equip_codes, zone_codes, session=session)
