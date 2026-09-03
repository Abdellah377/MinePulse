"""Run the deterministic optimizer against an alert. Persistence is append-only."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.optimization.compose import compose_operator_recommended_action
from app.optimization.dispatch_scope import APPLICABLE, NOT_APPLICABLE_TO_DISPATCH, assess_dispatch_scope
from app.optimization.eligibility import NOT_APPLICABLE as ELIG_NOT_APPLICABLE
from app.optimization.eligibility import eligibility_for_alert
from app.optimization.inputs import build_trusted_optimization_input
from app.optimization.persistence import latest_run_for_alert, list_runs_for_alert, persist_run, run_to_dict
from app.optimization.pending import attach_pending_projection
from app.optimization.solver import (
    DEFAULT_WEIGHTS,
    ERROR,
    NOT_APPLICABLE,
    OPTIMIZER_VERSION,
    _jsonable,
    dispatch_outcome,
    explain_run,
    generate_candidates,
    snapshot_digest,
)
from app.services.external_context.weather import get_weather_context
from app.services.operational.alerts import get_site_alert_or_404
from app.services.operational.context import OperationalContext

logger = logging.getLogger(__name__)


def _investigation_bundle(session: Session, ctx: OperationalContext, alert) -> dict | None:
    try:
        from app.ai.persistence import find_investigations

        rows = find_investigations(
            session,
            site_id=ctx.site_id,
            source_record_id=f"alert-{alert.alert_id}",
            shift_id=ctx.shift_id,
        )
    except Exception:
        logger.exception("optimization investigation lookup failed")
        return None
    if not isinstance(rows, (list, tuple)) or not rows:
        return None
    row = rows[0]
    recommendation = row.recommendation if isinstance(getattr(row, "recommendation", None), dict) else {}
    conclusion = row.conclusion if isinstance(getattr(row, "conclusion", None), dict) else {}
    return {"recommendation": recommendation, "conclusion": conclusion}


def _investigation_description(bundle: dict | None) -> str | None:
    if not bundle:
        return None
    recommendation = bundle.get("recommendation") if isinstance(bundle, dict) else None
    if not isinstance(recommendation, dict):
        return None
    text = recommendation.get("description")
    return str(text).strip() if text else None


def create_optimization_run(
    session: Session,
    ctx: OperationalContext,
    alert_id: str,
    *,
    extra_snapshot: dict | None = None,
) -> dict:
    alert = get_site_alert_or_404(session, ctx.site_id, alert_id)
    pk = alert.alert_id
    eligibility = eligibility_for_alert(alert)
    weights = dict(DEFAULT_WEIGHTS)
    weather_status = None
    investigation = _investigation_bundle(session, ctx, alert)
    description = _investigation_description(investigation)
    pipeline_stages: list[str] = []
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
        missing_reason = None
        candidates: list[dict] = []
        if eligibility == ELIG_NOT_APPLICABLE:
            pipeline_stages.append("context")
            outcome = NOT_APPLICABLE
        else:
            trusted = build_trusted_optimization_input(session, ctx, alert)
            snapshot.update(trusted.snapshot_fields)
            pipeline_stages.append("context")
            scope = assess_dispatch_scope(alert=alert, trusted=trusted, investigation=investigation)
            pipeline_stages.append("constraints")
            if scope != APPLICABLE:
                outcome = NOT_APPLICABLE_TO_DISPATCH if scope == NOT_APPLICABLE_TO_DISPATCH else NOT_APPLICABLE
                snapshot["dispatchScope"] = scope
            else:
                snapshot["dispatchScope"] = APPLICABLE
                candidates = generate_candidates(
                    truck=trusted.truck,
                    assignment=trusted.assignment,
                    loaders=trusted.loaders,
                    roads=trusted.roads,
                    zone_codes=trusted.zone_codes,
                    loading=trusted.loading,
                    origin_code=trusted.origin_code,
                    dest_code=trusted.dest_code,
                    weights=weights,
                    loader_zones=trusted.loader_zones,
                )
                pipeline_stages.append("candidates")
                candidates = attach_pending_projection(
                    candidates,
                    trusted.pending_commitments,
                    waiting_by_loader=trusted.waiting_by_loader,
                    service_minutes=trusted.loader_service_minutes,
                )
                outcome, missing_reason = dispatch_outcome(
                    truck=trusted.truck, dest=trusted.dest_code, candidates=candidates
                )
                pipeline_stages.append("ranking")
                pipeline_stages.append("impact")
        if extra_snapshot:
            snapshot.update(extra_snapshot)
        snapshot["pipelineStages"] = pipeline_stages
        explanation = explain_run(
            outcome=outcome,
            eligibility=eligibility,
            candidates=candidates,
            weights=weights,
            weather_status=weather_status,
            missing_reason=missing_reason,
        )
        recommended = next(
            (row for row in candidates if row.get("candidateId") == explanation.get("recommendedCandidateId")),
            None,
        )
        snapshot.setdefault("workflow", {})
        if isinstance(snapshot["workflow"], dict):
            snapshot["workflow"]["operatorRecommendedAction"] = compose_operator_recommended_action(
                eligibility=eligibility,
                outcome=outcome,
                operator_summary=None,
                recommended=recommended,
                investigation_description=description,
            )
            snapshot["workflow"]["pipelineStages"] = pipeline_stages
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("optimization run failed alert_id=%s", pk)
        if extra_snapshot:
            snapshot.update(extra_snapshot)
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


def persist_evaluated_run(
    session: Session,
    ctx: OperationalContext,
    *,
    alert_id: int,
    eligibility: str,
    outcome: str,
    candidates: list[dict],
    recommended_candidate_id: str | None,
    weather_status: str | None,
    snapshot: dict,
    weights: dict | None = None,
    explanation: dict | None = None,
) -> dict:
    resolved_weights = dict(weights or DEFAULT_WEIGHTS)
    resolved_explanation = explanation or explain_run(
        outcome=outcome,
        eligibility=eligibility,
        candidates=candidates,
        weights=resolved_weights,
        weather_status=weather_status,
    )
    if recommended_candidate_id is None:
        recommended_candidate_id = resolved_explanation.get("recommendedCandidateId")
    payload_snapshot = _jsonable({**snapshot, "explanation": resolved_explanation})
    row = persist_run(
        session,
        alert_id=alert_id,
        site_id=ctx.site_id,
        optimizer_version=OPTIMIZER_VERSION,
        weights=resolved_weights,
        eligibility=eligibility,
        outcome=outcome,
        snapshot_digest=snapshot_digest(snapshot),
        candidates=candidates,
        recommended_candidate_id=recommended_candidate_id,
        weather_status=weather_status,
        snapshot=payload_snapshot,
    )
    payload = run_to_dict(row)
    payload["explanation"] = resolved_explanation
    return payload


def list_optimization_runs(session: Session, ctx: OperationalContext, alert_id: str) -> list[dict]:
    alert = get_site_alert_or_404(session, ctx.site_id, alert_id)
    return [run_to_dict(row) for row in list_runs_for_alert(session, alert.alert_id)]


def latest_optimization_outcome(session: Session, alert_id: int) -> str | None:
    row = latest_run_for_alert(session, alert_id)
    return row.outcome if row is not None else None
