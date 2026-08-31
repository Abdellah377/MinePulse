"""Actions IA inbox: unresolved alerts as action cases. No LLM."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.persistence import find_investigations
from app.db.models import Alert, Equipment, Zone
from app.mappers.dto import alert_to_dto
from app.optimization.eligibility import OPTIMIZABLE, eligibility_for_alert
from app.optimization.persistence import latest_run_for_alert
from app.services.operational.alerts import ALERT_PAGE_DEFAULT, page_site_alerts
from app.services.operational.context import OperationalContext
from app.ai.feedback import load_decision_row, load_decision_row_for_alert, to_decision_record


def _code_maps(session: Session, ctx: OperationalContext) -> tuple[dict[int, str], dict[int, str]]:
    zones = session.scalars(select(Zone).where(Zone.site_id == ctx.site_id)).all()
    equipment = session.scalars(select(Equipment).where(Equipment.site_id == ctx.site_id)).all()
    return (
        {row.equipment_id: row.code for row in equipment},
        {row.zone_id: row.code for row in zones},
    )


def _inbox_flags(session: Session, alert: Alert, ctx: OperationalContext) -> dict:
    source_id = f"alert-{alert.alert_id}"
    investigations = find_investigations(session, site_id=ctx.site_id, source_record_id=source_id, shift_id=ctx.shift_id)
    latest = investigations[0] if investigations else None
    run = latest_run_for_alert(session, alert.alert_id)
    eligibility = eligibility_for_alert(alert)
    return {
        "hasInvestigation": latest is not None,
        "investigationId": str(latest.investigation_id) if latest is not None else None,
        "hasRecommendation": bool(latest is not None and latest.recommendation),
        "optimizationEligible": eligibility == OPTIMIZABLE,
        "eligibility": eligibility,
        "latestRunOutcome": run.outcome if run is not None else None,
        "latestRunId": str(run.run_id) if run is not None else None,
    }


def list_inbox(session: Session, ctx: OperationalContext, *, cursor: str | None = None, limit: int = ALERT_PAGE_DEFAULT) -> dict:
    page = page_site_alerts(session, ctx.site_id, limit=limit, cursor=cursor, active_only=True)
    equip_codes, zone_codes = _code_maps(session, ctx)
    items = []
    for alert in page["items"]:
        dto = alert_to_dto(alert, equip_codes, zone_codes, session=session)
        dto.update(_inbox_flags(session, alert, ctx))
        items.append(dto)
    return {
        "items": items,
        "nextCursor": page["nextCursor"],
        "hasMore": page["hasMore"],
        "activeCount": page["activeCount"],
    }


def inbox_detail(session: Session, ctx: OperationalContext, alert_id: str) -> dict:
    from app.services.operational.alerts import _parse_alert_pk

    pk = _parse_alert_pk(alert_id)
    alert = session.get(Alert, pk)
    if alert is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Alert not found")
    equip_codes, zone_codes = _code_maps(session, ctx)
    dto = alert_to_dto(alert, equip_codes, zone_codes, session=session)
    flags = _inbox_flags(session, alert, ctx)
    decision = None
    if flags["investigationId"]:
        from uuid import UUID

        row = load_decision_row(session, UUID(flags["investigationId"]))
        if row is not None:
            decision = to_decision_record(row).model_dump(mode="json")
    if decision is None:
        row = load_decision_row_for_alert(session, pk)
        if row is not None:
            decision = to_decision_record(row).model_dump(mode="json")
    run = latest_run_for_alert(session, pk)
    return {
        "alert": {**dto, **flags},
        "investigationId": flags["investigationId"],
        "decision": decision,
        "latestRun": {
            "runId": str(run.run_id),
            "outcome": run.outcome,
            "eligibility": run.eligibility,
            "candidates": run.candidates or [],
            "recommendedCandidateId": run.recommended_candidate_id,
            "weatherStatus": run.weather_status,
            "weights": run.weights or {},
            "optimizerVersion": run.optimizer_version,
            "createdAt": run.created_at.isoformat() if run.created_at else None,
            "explanation": (run.snapshot or {}).get("explanation"),
        }
        if run is not None
        else None,
    }
