"""Run the deterministic optimizer against an alert. Persistence is append-only."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.enums import EquipmentType
from app.db.models import Alert, Equipment
from app.optimization.eligibility import NOT_APPLICABLE as ELIG_NOT_APPLICABLE
from app.optimization.eligibility import eligibility_for_alert
from app.optimization.persistence import latest_run_for_alert, list_runs_for_alert, persist_run, run_to_dict
from app.optimization.solver import (
    DEFAULT_WEIGHTS,
    ERROR,
    FEASIBLE,
    INSUFFICIENT_DATA,
    NO_FEASIBLE_PLAN,
    NOT_APPLICABLE,
    OPTIMIZER_VERSION,
    _jsonable,
    explain_run,
    generate_candidates,
    snapshot_digest,
)
from app.services.external_context.weather import get_weather_context
from app.services.operational.alerts import _parse_alert_pk
from app.services.operational.assignments import current_assignment
from app.services.operational.context import OperationalContext
from app.services.operational.equipment import list_site_equipment
from app.services.operational.loading import loading_service_context
from app.services.operational.road_catalog import list_road_catalog, resolve_haul_endpoints

logger = logging.getLogger(__name__)


def create_optimization_run(session: Session, ctx: OperationalContext, alert_id: str) -> dict:
    pk = _parse_alert_pk(alert_id)
    alert = session.get(Alert, pk)
    if alert is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Alert not found")
    eligibility = eligibility_for_alert(alert)
    weights = dict(DEFAULT_WEIGHTS)
    weather_status = None
    snapshot: dict = {
        "siteId": ctx.site_id,
        "shiftId": ctx.shift_id,
        "simNow": ctx.sim_now.isoformat() if ctx.sim_now else None,
        "alertType": alert.alert_type,
        "eligibility": eligibility,
    }
    try:
        weather = get_weather_context(session, ctx.site_id)
        weather_status = weather.status.value
        snapshot["weather"] = {
            "status": weather_status,
            "unavailableReason": weather.unavailableReason,
            "condition": weather.current.condition if weather.current else None,
        }
        if eligibility == ELIG_NOT_APPLICABLE:
            outcome = NOT_APPLICABLE
            candidates: list[dict] = []
        else:
            equipment = list_site_equipment(session, ctx)
            by_id = {row.equipment_id: row for row in equipment}
            truck = by_id.get(alert.equipment_id) if alert.equipment_id else None
            assignment = current_assignment(session, truck.equipment_id, ctx) if truck else None
            roads, zone_by_id = list_road_catalog(session, ctx)
            zone_codes = {zone.zone_id: zone.code for zone in zone_by_id.values()}
            origin, dest = resolve_haul_endpoints(
                session,
                ctx,
                zone_by_id,
                equipment_id=truck.equipment_id if truck else None,
                zone_id=alert.zone_id,
            )
            if dest is None and assignment is not None and assignment.destination_zone_id is not None:
                dest = zone_codes.get(assignment.destination_zone_id)
            loading = loading_service_context(
                session,
                ctx,
                equipment_id=truck.equipment_id if truck else None,
                zone_id=alert.zone_id,
            )
            loaders = [row for row in equipment if row.type in {EquipmentType.EXCAVATOR, EquipmentType.LOADER}]
            snapshot.update(
                {
                    "truckId": truck.equipment_id if truck else None,
                    "truckCode": getattr(truck, "code", None),
                    "assignmentId": assignment.assignment_id if assignment else None,
                    "originZoneCode": origin,
                    "destZoneCode": dest,
                    "loaderCount": len(loaders),
                    "loadingLoaderCount": len(loading.get("loaders") or []),
                }
            )
            if truck is None or dest is None:
                outcome = INSUFFICIENT_DATA
                candidates = []
            else:
                candidates = generate_candidates(
                    truck=truck,
                    assignment=assignment,
                    loaders=loaders,
                    roads=roads,
                    zone_codes=zone_codes,
                    loading=loading,
                    origin_code=origin,
                    dest_code=dest,
                    weights=weights,
                )
                if not candidates:
                    outcome = NO_FEASIBLE_PLAN
                elif all(item.get("score") is None for item in candidates):
                    outcome = INSUFFICIENT_DATA
                else:
                    outcome = FEASIBLE
        explanation = explain_run(
            outcome=outcome,
            eligibility=eligibility,
            candidates=candidates,
            weights=weights,
            weather_status=weather_status,
        )
        digest = snapshot_digest(snapshot)
        row = persist_run(
            session,
            alert_id=pk,
            site_id=ctx.site_id,
            optimizer_version=OPTIMIZER_VERSION,
            weights=weights,
            eligibility=eligibility,
            outcome=outcome,
            snapshot_digest=digest,
            candidates=candidates,
            recommended_candidate_id=explanation["recommendedCandidateId"],
            weather_status=weather_status,
            snapshot=_jsonable({**snapshot, "explanation": explanation}),
        )
        payload = run_to_dict(row)
        payload["explanation"] = explanation
        return payload
    except Exception:
        logger.exception("optimization run failed alert_id=%s", pk)
        row = persist_run(
            session,
            alert_id=pk,
            site_id=ctx.site_id,
            optimizer_version=OPTIMIZER_VERSION,
            weights=weights,
            eligibility=eligibility,
            outcome=ERROR,
            snapshot_digest=snapshot_digest(snapshot),
            candidates=[],
            recommended_candidate_id=None,
            weather_status=weather_status,
            snapshot=_jsonable(snapshot),
        )
        payload = run_to_dict(row)
        payload["explanation"] = explain_run(
            outcome=ERROR,
            eligibility=eligibility,
            candidates=[],
            weights=weights,
            weather_status=weather_status,
        )
        return payload


def list_optimization_runs(session: Session, alert_id: str) -> list[dict]:
    pk = _parse_alert_pk(alert_id)
    return [run_to_dict(row) for row in list_runs_for_alert(session, pk)]


def latest_optimization_outcome(session: Session, alert_id: int) -> str | None:
    row = latest_run_for_alert(session, alert_id)
    return row.outcome if row is not None else None
