"""Trusted optimization input. All numerics come from operational services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import AlertStatus, EquipmentType
from app.db.models import Alert
from app.optimization.contracts import OptimizerId, payload_contains_forbidden_numeric_facts
from app.optimization.registry import catalog_for_planner
from app.optimization.solver import candidate_loader_ids
from app.services.operational.assignments import bulk_current_assignments, current_assignment
from app.services.operational.context import OperationalContext
from app.services.operational.equipment import latest_positions, list_site_equipment
from app.services.operational.loading import loading_service_context
from app.services.operational.road_catalog import list_road_catalog, resolve_haul_endpoints

MECHANICAL_RISK_TYPES = frozenset({"PREDICTED_MECHANICAL_FAILURE_RISK"})


@dataclass
class TrustedOptimizationInput:
    truck: Any
    assignment: Any
    loaders: list[Any]
    roads: list[dict]
    zone_codes: dict[int, str]
    loading: dict
    origin_code: str | None
    dest_code: str | None
    loader_zones: dict[int, str]
    candidate_loader_ids: list[int]
    mechanical_risk_loader_ids: set[int]
    planner_facts: dict[str, Any]
    snapshot_fields: dict[str, Any]
    evidence_ids: list[str] = field(default_factory=list)

    def as_engine_dict(self) -> dict[str, Any]:
        return {
            "truck": self.truck,
            "assignment": self.assignment,
            "loaders": self.loaders,
            "roads": self.roads,
            "zone_codes": self.zone_codes,
            "loading": self.loading,
            "origin_code": self.origin_code,
            "dest_code": self.dest_code,
            "loader_zones": self.loader_zones,
            "mechanical_risk_loader_ids": self.mechanical_risk_loader_ids,
        }


def _state_value(equipment: Any) -> str | None:
    if equipment is None:
        return None
    state = getattr(equipment, "current_state", None)
    if hasattr(state, "value"):
        return str(state.value)
    return str(state) if state is not None else None


def _type_value(equipment: Any) -> str | None:
    if equipment is None:
        return None
    eq_type = getattr(equipment, "type", None)
    if hasattr(eq_type, "value"):
        return str(eq_type.value)
    return str(eq_type) if eq_type is not None else None


def mechanical_risk_loader_ids(session: Session, ctx: OperationalContext) -> set[int]:
    rows = session.scalars(
        select(Alert).where(
            Alert.site_id == ctx.site_id,
            Alert.status != AlertStatus.RESOLVED,
            Alert.alert_type.in_(MECHANICAL_RISK_TYPES),
        )
    ).all()
    return {row.equipment_id for row in rows if row.equipment_id is not None}


def loader_zone_codes(
    session: Session,
    ctx: OperationalContext,
    equipment: list,
    zone_codes: dict[int, str],
) -> dict[int, str]:
    truck_ids = [row.equipment_id for row in equipment if row.type == EquipmentType.HAUL_TRUCK]
    loader_ids = {
        row.equipment_id
        for row in equipment
        if row.type in {EquipmentType.EXCAVATOR, EquipmentType.LOADER}
    }
    zones: dict[int, str] = {}
    for assignment in bulk_current_assignments(session, truck_ids, ctx).values():
        if assignment.loader_id not in loader_ids or assignment.origin_zone_id is None:
            continue
        code = zone_codes.get(assignment.origin_zone_id)
        if code and assignment.loader_id not in zones:
            zones[assignment.loader_id] = code
    positions = latest_positions(session, ctx.site_id)
    for loader_id in loader_ids:
        position = positions.get(loader_id)
        if position is None or position.zone_id is None:
            continue
        code = zone_codes.get(position.zone_id)
        if code:
            zones[loader_id] = code
    return zones


def build_trusted_optimization_input(session: Session, ctx: OperationalContext, alert: Any) -> TrustedOptimizationInput:
    equipment = list_site_equipment(session, ctx)
    by_id = {row.equipment_id: row for row in equipment}
    truck = by_id.get(alert.equipment_id) if getattr(alert, "equipment_id", None) else None
    assignment = current_assignment(session, truck.equipment_id, ctx) if truck else None
    roads, zone_by_id = list_road_catalog(session, ctx)
    zone_codes = {zone.zone_id: zone.code for zone in zone_by_id.values()}
    origin, dest = resolve_haul_endpoints(
        session,
        ctx,
        zone_by_id,
        equipment_id=truck.equipment_id if truck else None,
        zone_id=getattr(alert, "zone_id", None),
    )
    if dest is None and assignment is not None and assignment.destination_zone_id is not None:
        dest = zone_codes.get(assignment.destination_zone_id)
    loaders = [row for row in equipment if row.type in {EquipmentType.EXCAVATOR, EquipmentType.LOADER}]
    candidate_ids = candidate_loader_ids(assignment=assignment, loaders=loaders)
    loading = loading_service_context(
        session,
        ctx,
        equipment_id=truck.equipment_id if truck else None,
        zone_id=None,
        loader_ids=candidate_ids,
    )
    zones = loader_zone_codes(session, ctx, equipment, zone_codes)
    risk_ids = mechanical_risk_loader_ids(session, ctx)
    evidence_ids = [f"alert-{alert.alert_id}"]
    evidence_ids.extend(str(item) for item in (loading.get("sourceRecordIds") or []) if item)
    has_queue = any(int(row.get("waitingTruckCount") or 0) > 0 for row in (loading.get("loaders") or []))
    has_road_issue = any(str(row.get("status") or "") in {"RESTRICTED", "CLOSED"} for row in roads)
    zone_code = zone_codes.get(alert.zone_id) if getattr(alert, "zone_id", None) else None
    meta = getattr(alert, "metadata_", None) or getattr(alert, "metadata", None) or {}
    monitoring = meta.get("monitoring") if isinstance(meta, dict) else {}
    detector = None
    if isinstance(monitoring, dict):
        detector = monitoring.get("detectorId") or monitoring.get("detector_id")
    planner_facts = {
        "alertType": getattr(alert, "alert_type", None),
        "detectorId": detector,
        "siteId": ctx.site_id,
        "siteCode": ctx.site_code,
        "shiftId": ctx.shift_id,
        "zoneId": getattr(alert, "zone_id", None),
        "zoneCode": zone_code,
        "equipmentId": getattr(truck, "equipment_id", None) if truck else None,
        "equipmentCode": getattr(truck, "code", None) if truck else None,
        "equipmentType": _type_value(truck),
        "equipmentState": _state_value(truck),
        "hasQueueCondition": has_queue,
        "hasRoadRestrictionOrBlockage": has_road_issue,
        "hasMechanicalRiskAlert": bool(risk_ids),
        "registeredOptimizers": [item.value for item in OptimizerId],
        "optimizerCatalog": catalog_for_planner(),
        "evidenceIds": evidence_ids[:40],
    }
    if payload_contains_forbidden_numeric_facts(planner_facts):
        raise RuntimeError("planner facts must not include numeric optimizer inputs")
    snapshot_fields = {
        "truckId": truck.equipment_id if truck else None,
        "truckCode": getattr(truck, "code", None) if truck else None,
        "assignmentId": assignment.assignment_id if assignment else None,
        "originZoneCode": origin,
        "destZoneCode": dest,
        "loaderCount": len(loaders),
        "loadingLoaderCount": len(loading.get("loaders") or []),
        "candidateLoaderIds": candidate_ids,
        "loadingLoaderIds": [row.get("loaderId") for row in (loading.get("loaders") or [])],
        "loaderZones": zones,
        "mechanicalRiskLoaderIds": sorted(risk_ids),
        "plannerFacts": planner_facts,
    }
    return TrustedOptimizationInput(
        truck=truck,
        assignment=assignment,
        loaders=loaders,
        roads=roads,
        zone_codes=zone_codes,
        loading=loading,
        origin_code=origin,
        dest_code=dest,
        loader_zones=zones,
        candidate_loader_ids=candidate_ids,
        mechanical_risk_loader_ids=risk_ids,
        planner_facts=planner_facts,
        snapshot_fields=snapshot_fields,
        evidence_ids=evidence_ids,
    )
