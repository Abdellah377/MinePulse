from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import Ctx, DbSession
from app.db.models import HaulRoad, Shift, Zone
from app.mappers.dto import (
    alert_to_dto,
    enriched_equipment_dto,
    operator_to_dto,
    road_to_dto,
    shift_to_dto,
    site_to_dto,
    zone_to_dto,
)
from app.services.operational.alerts import list_site_alerts
from app.services.operational.assignments import operators_for_site_equipment
from app.services.operational.cycles import cycle_time_samples
from app.services.operational.downtime import downtime_reasons
from app.services.operational.equipment import (
    build_fleet_bulk_context,
    list_site_equipment,
    wait_idle_minutes_bulk,
)
from app.services.operational.production import production_summary
from app.services.operational.timeline import timeline_for_shift
from app.services.simulator_clock import simulation_control

router = APIRouter()


@router.get("/bootstrap")
def bootstrap(
    session: DbSession,
    ctx: Ctx,
    lite: bool = Query(False),
):
    """Single payload for frontend store hydration from PostgreSQL."""
    site = ctx.site
    zones = session.scalars(select(Zone).where(Zone.site_id == site.site_id, Zone.status == "ACTIVE")).all()
    roads = session.scalars(select(HaulRoad).where(HaulRoad.site_id == site.site_id)).all()
    equipment = list_site_equipment(session, ctx)
    shifts = session.scalars(
        select(Shift)
        .where(Shift.site_id == site.site_id)
        .order_by(Shift.shift_date.desc(), Shift.start_time)
    ).all()
    alerts = list_site_alerts(session, site.site_id)
    extra_op_ids = [a.assigned_to for a in alerts if a.assigned_to]
    operators = operators_for_site_equipment(
        session,
        [e.equipment_id for e in equipment],
        extra_operator_ids=extra_op_ids,
    )

    zone_codes = {z.zone_id: z.code for z in zones}
    zone_names = {z.zone_id: z.name for z in zones}
    equip_codes = {e.equipment_id: e.code for e in equipment}
    bulk = build_fleet_bulk_context(session, list(equipment), ctx)
    control = simulation_control()

    asn_by_op = {a.operator_id: a for a in bulk.assignments.values() if a.operator_id}
    operator_dtos = []
    for o in operators:
        asn = asn_by_op.get(o.operator_id)
        truck_id = asn.truck_id if asn else None
        idle = 0.0
        if truck_id is not None:
            _, idle = wait_idle_minutes_bulk(bulk, truck_id, ctx.shift_window_start, ctx.sim_now)
        operator_dtos.append(
            operator_to_dto(
                o,
                site_code=site.code,
                shift_dto_id=ctx.shift_dto_id,
                assigned_equipment_id=equip_codes.get(truck_id) if truck_id else None,
                cycles_this_shift=bulk.trips.get(truck_id, 0) if truck_id else 0,
                idle_minutes=idle,
            )
        )

    payload: dict = {
        "sites": [site_to_dto(site)],
        "shifts": [shift_to_dto(s) for s in shifts],
        "zones": [zone_to_dto(z, site.code) for z in zones],
        "routes": [road_to_dto(r, zone_codes, site.code) for r in roads],
        "equipment": [
            enriched_equipment_dto(
                session,
                e,
                bulk.positions.get(e.equipment_id),
                bulk.telemetry.get(e.equipment_id),
                zone_codes,
                bulk.trips,
                site_code=site.code,
                ctx=ctx,
                bulk=bulk,
            )
            for e in equipment
        ],
        "operators": operator_dtos,
        "alerts": [alert_to_dto(a, equip_codes, zone_codes, session=session) for a in alerts],
        "simNow": ctx.sim_now.isoformat(),
        "simulation": control,
        "activeSiteCode": ctx.site_code,
        "activeShiftId": ctx.shift_dto_id,
    }
    if not lite:
        payload["productionByShift"] = production_summary(session, ctx)
        payload["timelineSegments"] = timeline_for_shift(
            session, ctx, equip_codes, zone_names
        )
        payload["cycleTimeSamples"] = cycle_time_samples(session, ctx)
        payload["downtimeReasons"] = downtime_reasons(session, ctx)
    return payload
