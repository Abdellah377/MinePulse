"""Map ORM rows to frontend-compatible DTO dicts."""

from __future__ import annotations

from datetime import datetime, timezone

from geoalchemy2.shape import to_shape
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.db.models import (
    Alert,
    Cycle,
    CycleStage,
    Equipment,
    EquipmentPosition,
    EquipmentState as EquipmentStateRow,
    EquipmentTelemetry,
    HaulRoad,
    MaintenanceEvent,
    Operator,
    Shift,
    Site,
    Zone,
)
from app.mappers.enums import (
    ALERT_SEVERITY_TO_UI,
    ALERT_STATUS_TO_UI,
    EQUIPMENT_STATE_TO_UI,
    EQUIPMENT_TYPE_TO_UI,
    ZONE_TYPE_TO_UI,
)
from app.mappers.geo import lng_lat_to_workspace
from app.services.operational.context import OperationalContext, shift_window
from app.services.operational.clock import get_operational_now
from app.services.operational.alerts import alert_operational_time
from app.services.operational.cycles import avg_cycle_minutes_for_equipment
from app.services.operational.equipment import (
    FleetBulkContext,
    clip_interval_minutes,
    td_tu_pct,
    td_tu_pct_bulk,
    wait_idle_minutes_bulk,
)

CYCLE_UI_KEYS = [
    ("vide", EquipmentState.MOVING_EMPTY),
    ("attente_charge", EquipmentState.WAITING_LOADING),
    ("chargement", EquipmentState.LOADING),
    ("charge", EquipmentState.MOVING_LOADED),
    ("attente_dechargement", EquipmentState.WAITING_DUMPING),
    ("dechargement", EquipmentState.DUMPING),
]


def site_to_dto(site: Site) -> dict:
    return {
        "id": site.code,
        "databaseId": site.site_id,
        "name": site.name,
        "region": site.region,
        "pits": [],  # No persisted pit catalog exists yet.
    }


def shift_to_dto(shift: Shift, operational_now: datetime | None = None) -> dict:
    start, end = shift_window(shift, operational_now or get_operational_now())
    return {
        "id": f"shift-{shift.shift_id}",
        "databaseId": shift.shift_id,
        "windowStart": start.isoformat(),
        "windowEnd": end.isoformat(),
        "name": shift.name,
        "startHour": shift.start_time.hour,
        "endHour": shift.end_time.hour,
        "startMinute": shift.start_time.minute,
        "endMinute": shift.end_time.minute,
    }


def zone_to_dto(zone: Zone, site_code: str) -> dict:
    color = (zone.metadata_ or {}).get("color", "#2F6FED")
    ring: list[list[float]] = []
    try:
        poly = to_shape(zone.geometry)
        ring = [[float(c[0]), float(c[1])] for c in poly.exterior.coords]
    except Exception:
        pass
    points = [lng_lat_to_workspace(lng, lat) for lng, lat in ring] if ring else []
    return {
        "id": zone.code,
        "databaseId": zone.zone_id,
        "name": zone.name,
        "type": ZONE_TYPE_TO_UI.get(zone.type, "restreinte"),
        "points": points,
        "ringLngLat": [[lng, lat] for lng, lat in ring] if ring else None,
        "color": color,
        "description": zone.description or "",
        "capacity": zone.capacity,
        "siteId": site_code,
    }


def road_to_dto(road: HaulRoad, zone_codes: dict[int, str], site_code: str) -> dict:
    points: list[dict[str, float]] = []
    try:
        line = to_shape(road.geometry)
        points = [lng_lat_to_workspace(float(c[0]), float(c[1])) for c in line.coords]
    except Exception:
        pass
    return {
        "id": road.code,
        "fromZoneId": zone_codes.get(road.from_zone_id, ""),
        "toZoneId": zone_codes.get(road.to_zone_id, ""),
        "points": points,
        "distanceKm": float(road.distance_km) if road.distance_km is not None else None,
        "siteId": site_code,
    }


def _cycle_actuel(
    session: Session | None,
    equipment_id: int,
    *,
    bulk: FleetBulkContext | None = None,
    sim_now: datetime | None = None,
) -> list[dict]:
    cycle = None
    stages: list[CycleStage] = []
    if bulk is not None:
        cycle = bulk.active_cycles.get(equipment_id)
        if cycle:
            stages = bulk.cycle_stages.get(cycle.cycle_id, [])
    elif session is not None:
        cycle = session.scalar(
            select(Cycle)
            .where(Cycle.truck_id == equipment_id, Cycle.status == "ACTIVE")
            .order_by(Cycle.started_at.desc())
            .limit(1)
        )
        if cycle:
            stages = list(
                session.scalars(
                    select(CycleStage)
                    .where(CycleStage.cycle_id == cycle.cycle_id)
                    .order_by(CycleStage.sequence_no)
                ).all()
            )

    stages_by_state: dict[EquipmentState, CycleStage] = {}
    current_state = None
    for st in stages:
        stages_by_state[st.stage] = st
        if st.end_time is None:
            current_state = st.stage

    now = sim_now or _sim_now()
    out = []
    for key, estate in CYCLE_UI_KEYS:
        st = stages_by_state.get(estate)
        minutes = None
        if st and st.duration_sec is not None:
            minutes = round(st.duration_sec / 60, 1)
        elif st and st.end_time is None:
            minutes = round((now - st.start_time).total_seconds() / 60, 1)
        out.append(
            {
                "key": key,
                "minutes": minutes,
                "isCurrent": current_state == estate if current_state else False,
                "isOutlier": False,
            }
        )
    return out


def equipment_to_dto(
    eq: Equipment,
    pos: EquipmentPosition | None,
    tel: EquipmentTelemetry | None,
    zone_codes: dict[int, str],
    site_code: str,
    session: Session | None = None,
    trips_count: int = 0,
    wait_min: float = 0.0,
    idle_min: float = 0.0,
    destination_zone_id: str | None = None,
    operator_id: str | None = None,
    *,
    td_pct: float | None = None,
    tu_pct: float | None = None,
    health: float | None = None,
    cycle_avg: float | None = None,
    open_maintenance: bool = False,
    bulk: FleetBulkContext | None = None,
    ctx: OperationalContext | None = None,
) -> dict:
    position: dict[str, float] | None = None
    heading: float | None = None
    speed: float | None = None
    zone_id = None
    last_update: int | None = None
    if pos:
        try:
            pt = to_shape(pos.position)
            position = lng_lat_to_workspace(float(pt.x), float(pt.y))
            heading = float(pos.heading_deg) if pos.heading_deg is not None else None
        except Exception:
            position = None
        if pos.zone_id:
            zone_id = zone_codes.get(pos.zone_id)
        last_update = int(pos.ts.timestamp() * 1000)
    if tel is not None:
        tel_ms = int(tel.ts.timestamp() * 1000)
        last_update = max(last_update or 0, tel_ms) or tel_ms
        if tel.speed_kmh is not None:
            speed = float(tel.speed_kmh)
    fuel = float(tel.fuel_level_pct) if tel and tel.fuel_level_pct is not None else None
    payload = float(tel.payload_t) if tel and tel.payload_t is not None else None
    gasoil = float(tel.fuel_rate_lph) if tel and tel.fuel_rate_lph is not None else None
    odo = float(tel.odometer_km) if tel and tel.odometer_km is not None else None
    hours = float(tel.engine_hours) if tel and tel.engine_hours is not None else None
    state = EQUIPMENT_STATE_TO_UI.get(eq.current_state, "indetermine")
    engine_on: bool | None = None
    if eq.current_state in (EquipmentState.UNKNOWN, EquipmentState.NO_DATA):
        engine_on = None
    elif eq.current_state is not None:
        engine_on = state not in ("eteint", "aucune_donnee", "parking")
    cycle_actuel = _cycle_actuel(
        session, eq.equipment_id, bulk=bulk, sim_now=ctx.sim_now if ctx else None
    )

    if bulk is not None and ctx is not None:
        if wait_min == 0.0 and idle_min == 0.0:
            wait_min, idle_min = wait_idle_minutes_bulk(
                bulk, eq.equipment_id, ctx.shift_window_start, ctx.sim_now
            )
        if td_pct is None and tu_pct is None:
            td_pct, tu_pct = td_tu_pct_bulk(bulk, eq.equipment_id, ctx.shift_window_start, ctx.sim_now)
        if cycle_avg is None:
            cycle_avg = bulk.avg_cycle_min.get(eq.equipment_id)
        health = None
    elif session is not None and ctx is not None:
        if wait_min == 0.0 and idle_min == 0.0:
            wait_min, idle_min = _wait_idle_minutes(
                session, eq.equipment_id, ctx.shift_window_start, ctx.sim_now
            )
        if td_pct is None and tu_pct is None:
            td_pct, tu_pct = td_tu_pct(session, eq.equipment_id, ctx.shift_window_start, ctx.sim_now)
        health = None
        if cycle_avg is None:
            cycle_avg = avg_cycle_minutes_for_equipment(session, eq.equipment_id, ctx)

    capacity = float(eq.capacity_t) if eq.capacity_t is not None else None

    return {
        "id": eq.code,
        "databaseId": eq.equipment_id,
        "code": eq.code,
        "type": EQUIPMENT_TYPE_TO_UI.get(eq.type, "other"),
        "model": eq.model or "Unknown",
        "state": state,
        "position": position,
        "heading": heading,
        "speedKmh": speed,
        "fuelPct": fuel,
        "gasoilLph": gasoil,
        "tdPct": td_pct,
        "tuPct": tu_pct,
        "engineOn": engine_on,
        "operatorId": operator_id,
        "zoneId": zone_id,
        "destinationZoneId": destination_zone_id,
        "payloadTons": payload,
        "capacityTons": capacity,
        "odometerKm": odo,
        "engineHours": hours,
        "tripsThisShift": trips_count,
        "waitingMinutesThisShift": wait_min,
        "idleMinutesThisShift": idle_min,
        "lastUpdate": last_update,
        "siteId": site_code,
        "healthScore": health,
        "cycleActuel": cycle_actuel,
        "cycleDureeMoyenneMin": cycle_avg,
    }


def operator_to_dto(
    op: Operator,
    *,
    site_code: str | None = None,
    shift_dto_id: str | None = None,
    assigned_equipment_id: str | None = None,
    cycles_this_shift: int = 0,
    idle_minutes: float = 0.0,
) -> dict:
    cert_level = op.qualification
    status = "active" if op.active else "inactive"

    return {
        "id": op.employee_code,
        "name": op.full_name,
        "badgeId": op.employee_code,
        "certLevel": cert_level,
        "shiftId": shift_dto_id,
        "assignedEquipmentId": assigned_equipment_id,
        "cyclesThisShift": cycles_this_shift,
        "idleMinutes": idle_minutes,
        "performanceScore": None,
        "status": status,
        "siteId": site_code,
    }


def alert_to_dto(
    alert: Alert,
    equip_codes: dict[int, str],
    zone_codes: dict[int, str],
    session: Session | None = None,
) -> dict:
    eq_code = equip_codes.get(alert.equipment_id) if alert.equipment_id else None
    zone_code = zone_codes.get(alert.zone_id) if alert.zone_id else None
    occurred = int(alert_operational_time(alert).timestamp() * 1000)
    created = int(alert.created_at.timestamp() * 1000)
    updated = int((alert.resolved_at or alert.acknowledged_at or alert.created_at).timestamp() * 1000)
    meta = alert.metadata_ or {}
    assigned_label = meta.get("assigned_to_label")
    if assigned_label is None and alert.assigned_to and session is not None:
        op = session.get(Operator, alert.assigned_to)
        assigned_label = op.full_name if op else None
    return {
        "id": f"alert-{alert.alert_id}",
        "severity": ALERT_SEVERITY_TO_UI.get(alert.severity, "info"),
        "status": ALERT_STATUS_TO_UI.get(alert.status, "new"),
        "title": alert.title,
        "description": alert.description or "",
        "equipmentId": eq_code,
        "zoneId": zone_code,
        "location": zone_code or "Site",
        "category": alert.alert_type,
        "occurredAt": occurred,
        "createdAt": created,
        "updatedAt": updated,
        "assignedTo": assigned_label,
        "resolution": meta.get("resolution"),
    }


def _sim_now() -> datetime:
    return get_operational_now()


def _health_score(
    eq: Equipment,
    tel: EquipmentTelemetry | None,
    td_pct: float,
    *,
    open_maintenance: bool,
) -> float:
    score = 88.0
    state = eq.current_state
    if state in (EquipmentState.STOPPED_MECHANICAL, EquipmentState.MAINTENANCE):
        score = 35.0
    elif state == EquipmentState.NO_DATA:
        score = 45.0
    elif state in (EquipmentState.STOPPED_UNDEFINED, EquipmentState.STOPPED_EXTERNAL):
        score = 55.0
    elif state == EquipmentState.ENGINE_OFF:
        score = 50.0
    else:
        score = 55.0 + td_pct * 0.4

    fuel = float(tel.fuel_level_pct) if tel and tel.fuel_level_pct is not None else None
    if fuel is not None:
        if fuel < 15:
            score -= 20
        elif fuel < 30:
            score -= 10

    if open_maintenance:
        score = min(score, 40.0)

    return round(min(99.0, max(5.0, score)), 0)


def _wait_idle_minutes(
    session: Session, equipment_id: int, since: datetime, until: datetime
) -> tuple[float, float]:
    wait_states = {EquipmentState.WAITING_LOADING, EquipmentState.WAITING_DUMPING}
    idle_states = {
        EquipmentState.STOPPED_OPERATIONAL,
        EquipmentState.STOPPED_MECHANICAL,
        EquipmentState.STOPPED_EXTERNAL,
        EquipmentState.STOPPED_UNDEFINED,
        EquipmentState.MAINTENANCE,
        EquipmentState.PARKED,
        EquipmentState.ENGINE_OFF,
    }
    rows = session.scalars(
        select(EquipmentStateRow).where(
            EquipmentStateRow.equipment_id == equipment_id,
            EquipmentStateRow.start_time < until,
            or_(EquipmentStateRow.end_time.is_(None), EquipmentStateRow.end_time > since),
        )
    ).all()
    wait = idle = 0.0
    for r in rows:
        mins = clip_interval_minutes(r.start_time, r.end_time, since, until)
        if r.state in wait_states:
            wait += mins
        elif r.state in idle_states:
            idle += mins
    return round(wait, 1), round(idle, 1)


def maintenance_history_for_equipment(session: Session, equipment_id: int, limit: int = 10) -> list[dict]:
    rows = session.scalars(
        select(MaintenanceEvent)
        .where(MaintenanceEvent.equipment_id == equipment_id)
        .order_by(MaintenanceEvent.start_time.desc())
        .limit(limit)
    ).all()
    out: list[dict] = []
    for m in rows:
        dur_h = (m.actual_end_time - m.start_time).total_seconds() / 3600 if m.actual_end_time else None
        meta = m.metadata_ or {}
        out.append(
            {
                "id": f"mnt-{m.maintenance_id}",
                "date": int(m.start_time.timestamp() * 1000),
                "type": m.type + (f" — {m.component}" if m.component else ""),
                "durationH": round(dur_h, 1) if dur_h is not None else None,
                "technician": meta.get("technician"),
            }
        )
    return out


def enriched_equipment_dto(
    session: Session,
    eq: Equipment,
    pos: EquipmentPosition | None,
    tel: EquipmentTelemetry | None,
    zone_codes: dict[int, str],
    trips: dict[int, int],
    *,
    site_code: str,
    ctx: OperationalContext,
    bulk: FleetBulkContext | None = None,
) -> dict:
    if bulk is not None:
        asn = bulk.assignments.get(eq.equipment_id)
        op = (
            bulk.operators.get(asn.operator_id)
            if asn and asn.operator_id
            else None
        )
    else:
        from app.services.operational.assignments import current_assignment

        asn = current_assignment(session, eq.equipment_id, ctx)
        op = session.get(Operator, asn.operator_id) if asn and asn.operator_id else None
    dest_code = zone_codes.get(asn.destination_zone_id) if asn and asn.destination_zone_id else None
    operator_id = op.employee_code if op else None
    return equipment_to_dto(
        eq,
        pos,
        tel,
        zone_codes,
        site_code,
        session=session,
        trips_count=trips.get(eq.equipment_id, 0),
        destination_zone_id=dest_code,
        operator_id=operator_id,
        bulk=bulk,
        ctx=ctx,
    )
