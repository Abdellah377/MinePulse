"""Thin evidence adapters over MinePulse's authoritative operational services."""

from __future__ import annotations

from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session

from app.ai.contracts import EvidenceItem, EvidenceKind
from app.services.operational import alerts as alert_service
from app.services.operational import assignments as assignment_service
from app.services.operational import cycles as cycle_service
from app.services.operational import downtime as downtime_service
from app.services.operational import equipment as equipment_service
from app.services.operational import loading as loading_service
from app.services.operational import production as production_service
from app.services.operational import road_catalog
from app.services.operational import timeline as timeline_service
from app.services.operational import zones as zone_service
from app.services.operational.context import OperationalContext
from app.services.operational.road_network import build_route_context


def _evidence(
    ctx: OperationalContext,
    *,
    kind: EvidenceKind,
    tool: str,
    service: str,
    metric: str,
    value,
    available: bool = True,
    unit: str | None = None,
    equipment_id: int | None = None,
    zone_id: int | None = None,
    source_record_ids: list[str] | None = None,
    metadata: dict | None = None,
    notes: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        kind=kind,
        source_tool=tool,
        source_service=service,
        metric=metric,
        value=to_jsonable_python(value) if available else None,
        available=available,
        unit=unit,
        site_id=ctx.site_id,
        shift_id=ctx.shift_id,
        equipment_id=equipment_id,
        zone_id=zone_id,
        observed_at=ctx.sim_now,
        source_record_ids=source_record_ids or [],
        metadata=to_jsonable_python(metadata or {}),
        notes=notes,
    )


def context_evidence(ctx: OperationalContext) -> EvidenceItem:
    value = {
        "siteId": ctx.site_id,
        "siteCode": ctx.site_code,
        "siteName": ctx.site.name,
        "shiftId": ctx.shift_id,
        "shiftName": ctx.shift.name if ctx.shift else None,
        "operationalNow": ctx.sim_now,
        "windowStart": ctx.shift_window_start,
        "windowEnd": ctx.shift_window_end,
    }
    ids = [f"site:{ctx.site_id}"]
    if ctx.shift_id is not None:
        ids.append(f"shift:{ctx.shift_id}")
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="operational_context",
        service="app.services.operational.context.get_operational_context",
        metric="operational_context",
        value=value,
        source_record_ids=ids,
    )


def shift_production(session: Session, ctx: OperationalContext) -> EvidenceItem:
    value = production_service.production_summary(session, ctx)
    if ctx.shift_id is None:
        return _evidence(
            ctx,
            kind=EvidenceKind.DERIVED_METRIC,
            tool="shift_production",
            service="app.services.operational.production.production_summary",
            metric="shift_production_summary",
            value=None,
            available=False,
            notes="No shift could be resolved; production summary is unavailable.",
        )
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="shift_production",
        service="app.services.operational.production.production_summary",
        metric="shift_production_summary",
        value=value,
        unit="tonnes",
        source_record_ids=[f"shift:{ctx.shift_id}"],
    )


def _equipment_rows(session: Session, ctx: OperationalContext, equipment_id: int | None = None):
    equipment = equipment_service.list_site_equipment(session, ctx, active_only=True)
    if equipment_id is not None:
        equipment = [item for item in equipment if item.equipment_id == equipment_id]
    return equipment


def fleet_snapshot(
    session: Session,
    ctx: OperationalContext,
    *,
    equipment_id: int | None = None,
) -> EvidenceItem:
    equipment = _equipment_rows(session, ctx, equipment_id)
    if equipment_id is not None and not equipment:
        return _evidence(
            ctx,
            kind=EvidenceKind.DERIVED_METRIC,
            tool="fleet_snapshot",
            service="app.services.operational.equipment.build_fleet_bulk_context",
            metric="fleet_snapshot",
            value=None,
            available=False,
            equipment_id=equipment_id,
            notes="Equipment is not active at the investigation site or does not exist.",
        )
    bulk = equipment_service.build_fleet_bulk_context(session, equipment, ctx)
    rows = []
    for eq in equipment:
        eq_id = eq.equipment_id
        assignment = bulk.assignments.get(eq_id)
        telemetry = bulk.telemetry.get(eq_id)
        has_state_history = bool(bulk.state_rows.get(eq_id))
        waiting, idle = (None, None)
        if has_state_history:
            waiting, idle = equipment_service.wait_idle_minutes_bulk(
                bulk, eq_id, ctx.shift_window_start, ctx.sim_now
            )
        rows.append(
            {
                "equipmentId": eq_id,
                "code": eq.code,
                "type": eq.type.value,
                "currentState": eq.current_state.value,
                "tripsThisShift": bulk.trips.get(eq_id, 0),
                "averageCycleMinutes": bulk.avg_cycle_min.get(eq_id),
                "waitingMinutesThisShift": waiting,
                "idleMinutesThisShift": idle,
                "stateHistoryAvailable": has_state_history,
                "latestTelemetryAt": telemetry.ts if telemetry else None,
                "openMaintenance": eq_id in bulk.open_maintenance,
                "assignment": (
                    {
                        "assignmentId": assignment.assignment_id,
                        "loaderId": assignment.loader_id,
                        "operatorId": assignment.operator_id,
                        "originZoneId": assignment.origin_zone_id,
                        "destinationZoneId": assignment.destination_zone_id,
                        "assignedAt": assignment.assigned_at,
                        "status": assignment.status,
                    }
                    if assignment
                    else None
                ),
            }
        )
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="fleet_snapshot",
        service="app.services.operational.equipment.build_fleet_bulk_context",
        metric="fleet_snapshot",
        value=rows,
        equipment_id=equipment_id,
        source_record_ids=[f"equipment:{e.equipment_id}" for e in equipment],
        metadata={"equipmentCount": len(rows)},
    )


def cycle_performance(session: Session, ctx: OperationalContext) -> EvidenceItem:
    samples = cycle_service.cycle_time_samples(session, ctx, limit=100)
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="cycle_performance",
        service="app.services.operational.cycles.cycle_time_samples",
        metric="completed_cycle_time_samples",
        value=samples,
        unit="minutes",
        metadata={"sampleCount": len(samples)},
    )


def downtime(session: Session, ctx: OperationalContext) -> EvidenceItem:
    rows = downtime_service.downtime_reasons(session, ctx)
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="downtime",
        service="app.services.operational.downtime.downtime_reasons",
        metric="downtime_by_reason",
        value=rows,
        unit="hours",
    )


def site_alerts(session: Session, ctx: OperationalContext) -> EvidenceItem:
    alerts = alert_service.list_site_alerts(session, ctx.site_id, active_only=True)
    value = [
        {
            "alertId": alert.alert_id,
            "occurredAt": alert_service.alert_operational_time(alert),
            "persistedAt": alert.created_at,
            "source": alert.source.value,
            "severity": alert.severity.value,
            "status": alert.status.value,
            "alertType": alert.alert_type,
            "title": alert.title,
            "description": alert.description,
            "equipmentId": alert.equipment_id,
            "zoneId": alert.zone_id,
            "confidence": float(alert.confidence) if alert.confidence is not None else None,
        }
        for alert in alerts
    ]
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="site_alerts",
        service="app.services.operational.alerts.list_site_alerts",
        metric="active_site_alerts",
        value=value,
        source_record_ids=[f"alert:{a.alert_id}" for a in alerts],
    )


def assignments(
    session: Session,
    ctx: OperationalContext,
    *,
    equipment_id: int | None = None,
) -> EvidenceItem:
    equipment = _equipment_rows(session, ctx, equipment_id)
    ids = [e.equipment_id for e in equipment]
    rows = assignment_service.bulk_current_assignments(session, ids, ctx)
    value = [
        {
            "assignmentId": row.assignment_id,
            "truckId": row.truck_id,
            "loaderId": row.loader_id,
            "operatorId": row.operator_id,
            "originZoneId": row.origin_zone_id,
            "destinationZoneId": row.destination_zone_id,
            "assignedAt": row.assigned_at,
            "status": row.status,
        }
        for row in rows.values()
    ]
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="assignments",
        service="app.services.operational.assignments.bulk_current_assignments",
        metric="current_assignments",
        value=value,
        equipment_id=equipment_id,
        source_record_ids=[f"assignment:{row.assignment_id}" for row in rows.values()],
    )


def equipment_timeline(
    session: Session,
    ctx: OperationalContext,
    *,
    equipment_id: int | None = None,
) -> EvidenceItem:
    equipment = _equipment_rows(session, ctx)
    zones = zone_service.list_zones(session, ctx)
    codes = {e.equipment_id: e.code for e in equipment}
    zone_names = {z.zone_id: z.name for z in zones}
    rows = timeline_service.timeline_for_shift(session, ctx, codes, zone_names)
    if equipment_id is not None:
        code = codes.get(equipment_id)
        if code is None:
            return _evidence(
                ctx,
                kind=EvidenceKind.FACT,
                tool="equipment_timeline",
                service="app.services.operational.timeline.timeline_for_shift",
                metric="equipment_state_timeline",
                value=None,
                available=False,
                equipment_id=equipment_id,
                notes="Equipment is not active at the investigation site or does not exist.",
            )
        rows = [row for row in rows if row["equipmentId"] == code]
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="equipment_timeline",
        service="app.services.operational.timeline.timeline_for_shift",
        metric="equipment_state_timeline",
        value=rows,
        equipment_id=equipment_id,
        source_record_ids=[str(row["id"]) for row in rows],
    )


def loading_context(
    session: Session,
    ctx: OperationalContext,
    *,
    equipment_id: int | None = None,
    zone_id: int | None = None,
) -> EvidenceItem:
    result = loading_service.loading_service_context(
        session,
        ctx,
        equipment_id=equipment_id,
        zone_id=zone_id,
    )
    value = {key: item for key, item in result.items() if key != "sourceRecordIds"}
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="loading_context",
        service="app.services.operational.loading.loading_service_context",
        metric="loading_queue_and_service_context",
        value=value,
        equipment_id=equipment_id,
        zone_id=zone_id,
        source_record_ids=result["sourceRecordIds"],
        metadata={
            "windowStart": ctx.shift_window_start,
            "windowEnd": ctx.sim_now,
            "loaderCount": len(result["loaders"]),
            "bounds": result["bounds"],
        },
        notes="Observed assignments, queues, states, and loading stages; no causal inference.",
    )


def zone_context(
    session: Session,
    ctx: OperationalContext,
    *,
    zone_id: int | None = None,
) -> EvidenceItem:
    zones = zone_service.list_zones(session, ctx)
    if zone_id is not None:
        zones = [zone for zone in zones if zone.zone_id == zone_id]
    if zone_id is not None and not zones:
        return _evidence(
            ctx,
            kind=EvidenceKind.FACT,
            tool="zone_context",
            service="app.services.operational.zones.list_zones",
            metric="zone_context",
            value=None,
            available=False,
            zone_id=zone_id,
            notes="Zone is not active at the investigation site or does not exist.",
        )
    value = [
        {
            "zoneId": zone.zone_id,
            "code": zone.code,
            "name": zone.name,
            "type": zone.type.value,
            "capacity": zone.capacity,
            "priority": zone.priority,
            "status": zone.status,
        }
        for zone in zones
    ]
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="zone_context",
        service="app.services.operational.zones.list_zones",
        metric="zone_context",
        value=value,
        zone_id=zone_id,
        source_record_ids=[f"zone:{z.zone_id}" for z in zones],
    )


def road_network_context(
    session: Session,
    ctx: OperationalContext,
    *,
    equipment_id: int | None = None,
    zone_id: int | None = None,
    parameters: list[str] | None = None,
) -> EvidenceItem:
    catalog, zone_by_id = road_catalog.list_road_catalog(session, ctx)
    if not catalog:
        return _evidence(
            ctx,
            kind=EvidenceKind.FACT,
            tool="road_network_context",
            service="app.services.operational.road_network.build_route_context",
            metric="road_network_context",
            value=None,
            available=False,
            equipment_id=equipment_id,
            zone_id=zone_id,
            notes="No haul roads are recorded for this site.",
        )
    origin, destination = road_catalog.resolve_haul_endpoints(
        session,
        ctx,
        zone_by_id,
        equipment_id=equipment_id,
        zone_id=zone_id,
        parameters=parameters,
    )
    payload = build_route_context(catalog, origin_zone_id=origin, destination_zone_id=destination)
    codes = {zone.code: zone for zone in zone_by_id.values()}
    if origin and origin in codes:
        payload["originZone"] = road_catalog.zone_brief(codes[origin])
    if destination and destination in codes:
        payload["destinationZone"] = road_catalog.zone_brief(codes[destination])
    payload["zoneDescriptionIsNotARoutingRule"] = True
    notes = (
        "Operational haul-road facts. CLOSED and unknown-status roads are not routable. "
        "RESTRICTED roads may be used but are not equivalent to OPEN. "
        "Zone descriptions are context only and do not override road status. "
        "Candidate distances and travel times are precomputed; do not recalculate them."
    )
    if origin is None or destination is None:
        notes += " Origin or destination could not be fully resolved."
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="road_network_context",
        service="app.services.operational.road_network.build_route_context",
        metric="road_network_context",
        value=payload,
        equipment_id=equipment_id,
        zone_id=zone_id,
        source_record_ids=[f"road:{item['id']}" for item in payload.get("relevantRoads", []) if item.get("id")],
        metadata={
            "candidatePathCount": len(payload.get("candidatePaths") or []),
            "relevantRoadCount": len(payload.get("relevantRoads") or []),
        },
        notes=notes,
    )
