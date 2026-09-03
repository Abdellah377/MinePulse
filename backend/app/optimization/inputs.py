"""Trusted optimization input. All numerics come from operational services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.enums import AlertStatus, EquipmentType
from app.db.models import Alert, AiRecommendationDecision, Equipment
from app.optimization.pending import loader_id_from_payload, pending_commitment_counts
from app.optimization.contracts import OptimizerId, payload_contains_forbidden_numeric_facts
from app.optimization.location import collect_loader_locations
from app.optimization.registry import catalog_for_planner
from app.optimization.solver import candidate_loader_ids
from app.services.operational.assignments import current_assignment
from app.services.operational.context import OperationalContext
from app.services.operational.equipment import latest_positions, list_site_equipment
from app.services.operational.loading import loading_service_context
from app.services.operational.road_catalog import list_road_catalog, resolve_haul_endpoints

_LOADER_TYPES = {EquipmentType.EXCAVATOR, EquipmentType.LOADER}

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
    loader_location_sources: dict[int, str] = field(default_factory=dict)
    pending_commitments: dict[int, int] = field(default_factory=dict)
    waiting_by_loader: dict[int, int] = field(default_factory=dict)
    loader_service_minutes: float | None = None

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
            "loader_location_sources": self.loader_location_sources,
            "mechanical_risk_loader_ids": self.mechanical_risk_loader_ids,
            "pending_commitments": self.pending_commitments,
            "waiting_by_loader": self.waiting_by_loader,
            "loader_service_minutes": self.loader_service_minutes,
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


def filter_mechanical_risk_loader_ids(ids: set[int], equipment: list) -> set[int]:
    loader_ids = {
        row.equipment_id
        for row in equipment
        if getattr(row, "type", None) in _LOADER_TYPES and getattr(row, "equipment_id", None) is not None
    }
    return {eid for eid in ids if eid in loader_ids}


def mechanical_risk_loader_ids(session: Session, ctx: OperationalContext, equipment: list | None = None) -> set[int]:
    rows = session.scalars(
        select(Alert).join(Equipment, Equipment.equipment_id == Alert.equipment_id).where(
            Alert.site_id == ctx.site_id,
            Alert.status != AlertStatus.RESOLVED,
            Alert.alert_type.in_(MECHANICAL_RISK_TYPES),
            Equipment.type.in_(_LOADER_TYPES),
        )
    ).all()
    ids = {row.equipment_id for row in rows if row.equipment_id is not None}
    if equipment is None:
        return ids
    return filter_mechanical_risk_loader_ids(ids, equipment)


def loader_zone_codes(
    session: Session,
    ctx: OperationalContext,
    equipment: list,
    zone_codes: dict[int, str],
) -> dict[int, str]:
    zones, _sources = loader_locations(session, ctx, equipment, zone_codes)
    return zones


def loader_locations(
    session: Session,
    ctx: OperationalContext,
    equipment: list,
    zone_codes: dict[int, str],
) -> tuple[dict[int, str], dict[int, str]]:
    loaders = [row for row in equipment if getattr(row, "type", None) in _LOADER_TYPES]
    positions = latest_positions(session, ctx.site_id)
    stale_seconds = float(get_settings().monitoring_telemetry_stale_seconds)
    return collect_loader_locations(
        loaders=loaders,
        positions=positions,
        zone_codes=zone_codes,
        now=ctx.sim_now,
        stale_seconds=stale_seconds,
    )


def _pending_commitments(session: Session, ctx: OperationalContext) -> dict[int, int]:
    rows = session.scalars(
        select(AiRecommendationDecision).where(
            AiRecommendationDecision.site_id == ctx.site_id,
            AiRecommendationDecision.follow_up_status == "OPEN",
            AiRecommendationDecision.decision_type.in_(("ACCEPTED", "MODIFIED")),
        )
    ).all()
    payloads = [
        {
            "decisionType": row.decision_type,
            "followUpStatus": row.follow_up_status,
            "originalRecommendation": row.original_recommendation,
            "loaderId": loader_id_from_payload(row.operator_action)
            or loader_id_from_payload(row.original_recommendation),
        }
        for row in rows
    ]
    return pending_commitment_counts(payloads)


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
    loaders = [row for row in equipment if row.type in _LOADER_TYPES]
    candidate_ids = candidate_loader_ids(assignment=assignment, loaders=loaders)
    loading = loading_service_context(
        session,
        ctx,
        equipment_id=truck.equipment_id if truck else None,
        zone_id=None,
        loader_ids=candidate_ids,
    )
    zones, location_sources = loader_locations(session, ctx, equipment, zone_codes)
    risk_ids = mechanical_risk_loader_ids(session, ctx, equipment)
    pending = _pending_commitments(session, ctx)
    waiting_by_loader = {
        int(row["loaderId"]): int(row.get("waitingTruckCount") or 0)
        for row in (loading.get("loaders") or [])
        if row.get("loaderId") is not None
    }
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
        "loaderLocationSources": {str(loader_id): source for loader_id, source in location_sources.items()},
        "mechanicalRiskLoaderIds": sorted(risk_ids),
        "pendingCommitments": {str(loader_id): count for loader_id, count in pending.items()},
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
        loader_location_sources=location_sources,
        pending_commitments=pending,
        waiting_by_loader=waiting_by_loader,
        loader_service_minutes=None,
    )
