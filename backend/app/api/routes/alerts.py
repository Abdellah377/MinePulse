from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.mappers.dto import alert_to_dto
from app.schemas.alerts import AlertPatchRequest
from app.services.operational.alerts import update_alert
from sqlalchemy import select
from app.db.models import Alert, Equipment, Zone

router = APIRouter()


@router.patch("/{alert_id}")
def patch_alert(alert_id: str, body: AlertPatchRequest, session: DbSession, ctx: Ctx):
    alert = update_alert(
        session,
        alert_id,
        status=body.status,
        assigned_to_operator_id=body.assigned_to_operator_id,
        actor_label=body.actor_label,
        resolution=body.resolution,
    )
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    equipment = session.scalars(select(Equipment).where(Equipment.site_id == ctx.site_id)).all()
    zone_codes = {z.zone_id: z.code for z in zones}
    equip_codes = {e.equipment_id: e.code for e in equipment}
    return alert_to_dto(alert, equip_codes, zone_codes, session=session)
