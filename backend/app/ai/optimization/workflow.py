"""Bounded planner → engines → reviewer workflow. Max two optimizer executions."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ai.lifecycle import investigation_gate
from app.ai.persistence import find_investigations
from app.ai.llm.provider import (
    LLMProvider,
    LLMProviderError,
    budget_allows_attempt,
    create_llm_provider,
)
from app.ai.optimization.planner import planner_payload_from_facts, sanitize_planner_decision
from app.ai.optimization.reviewer import sanitize_review
from app.config import get_settings
from app.optimization.compose import (
    DETERMINISTIC_ONLY_COPY,
    NO_CHANGE_OPERATOR_COPY,
    ORCHESTRATOR_VERSION,
    REVIEW_UNAVAILABLE_COPY,
    compose_operator_recommended_action,
    execute_selected_engines,
    finalize_recommendations,
)
from app.optimization.contracts import (
    ConstraintCode,
    OptimizationPlannerDecision,
    OptimizationReview,
    ReviewStatus,
    WorkflowStatus,
)
from app.optimization.eligibility import NOT_APPLICABLE as ELIG_NOT_APPLICABLE
from app.optimization.eligibility import eligibility_for_alert
from app.optimization.inputs import build_trusted_optimization_input
from app.optimization.rca_gate import apply_rca_excludes, rca_constraints
from app.optimization.registry import get_spec
from app.optimization.service import create_optimization_run, persist_evaluated_run
from app.optimization.solver import DEFAULT_WEIGHTS, FEASIBLE, NOT_APPLICABLE, dispatch_outcome, explain_run
from app.services.external_context.weather import get_weather_context
from app.services.operational.alerts import get_site_alert_or_404
from app.services.operational.context import OperationalContext

logger = logging.getLogger(__name__)

MAX_OPTIMIZATION_PASSES = 2


def _dump(model: Any) -> dict:
    if model is None:
        return {}
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return dict(model)


def _ms(started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _can_spend_llm(provider: Any) -> bool:
    remaining = getattr(provider, "_remaining_seconds", None)
    timeout = getattr(provider, "_timeout_seconds", None)
    if remaining is None or timeout is None:
        return True
    return budget_allows_attempt(float(remaining), float(timeout))


def _provider_meta(provider: LLMProvider | None) -> dict[str, Any]:
    if provider is None:
        return {"provider": None, "model": None}
    metrics = getattr(provider, "last_call_metrics", None) or {}
    meta = {
        "provider": metrics.get("provider") or getattr(provider, "provider_name", None),
        "model": metrics.get("model") or getattr(provider, "model_name", None),
    }
    if metrics.get("fallback_occurred") is not None:
        meta["fallbackOccurred"] = metrics.get("fallback_occurred")
    if metrics.get("configured_providers") is not None:
        meta["configuredProviders"] = metrics.get("configured_providers")
    if metrics.get("final_provider") is not None:
        meta["finalProvider"] = metrics.get("final_provider")
    if metrics.get("remaining_budget_ms") is not None:
        meta["remainingBudgetMs"] = metrics.get("remaining_budget_ms")
    if metrics.get("cooldown_skipped") is not None:
        meta["cooldownSkipped"] = metrics.get("cooldown_skipped")
    attempts = metrics.get("attempts")
    if isinstance(attempts, list):
        meta["attemptCount"] = len(attempts)
        meta["attempts"] = [
            {
                "provider": item.get("provider"),
                "model": item.get("model"),
                "attempt": item.get("attempt"),
                "duration_ms": item.get("duration_ms"),
                "http_status_class": item.get("http_status_class"),
                "failure_category": item.get("failure_category"),
            }
            for item in attempts
            if isinstance(item, dict)
        ]
    return meta


def _candidate_review_payload(candidates: list[dict]) -> list[dict]:
    keys = (
        "candidateId",
        "loaderId",
        "loaderCode",
        "destZoneCode",
        "originZoneCode",
        "roadIds",
        "distanceKm",
        "travelMinutes",
        "waitMinutes",
        "score",
        "constraintNotes",
        "isCurrent",
        "rank",
        "rankReason",
        "candidateRelation",
    )
    return [{key: row.get(key) for key in keys} for row in candidates]


def _equipment_type_for(trusted: Any, equipment_id: int | None) -> Any:
    if equipment_id is None:
        return None
    for row in list(getattr(trusted, "loaders", None) or []):
        if getattr(row, "equipment_id", None) == equipment_id:
            return getattr(row, "type", None)
    truck = getattr(trusted, "truck", None)
    if truck is not None and getattr(truck, "equipment_id", None) == equipment_id:
        return getattr(truck, "type", None)
    return None


def _rca_from_investigation(session: Session, ctx: OperationalContext, alert: Any, trusted: Any):
    empty = rca_constraints(
        diagnosis_status=None,
        reliable_root_cause=False,
        equipment_id=None,
        equipment_type=None,
    )
    try:
        rows = find_investigations(
            session,
            site_id=ctx.site_id,
            source_record_id=f"alert-{alert.alert_id}",
            shift_id=ctx.shift_id,
        )
    except Exception:
        logger.exception("rca investigation lookup failed")
        return empty
    if not isinstance(rows, (list, tuple)) or not rows:
        return empty
    row = rows[0]
    conclusion = row.conclusion if isinstance(getattr(row, "conclusion", None), dict) else {}
    recommendation = row.recommendation if isinstance(getattr(row, "recommendation", None), dict) else {}
    raw_equipment_id = recommendation.get("target_equipment_id") or getattr(row, "equipment_id", None)
    try:
        equipment_id = int(raw_equipment_id) if raw_equipment_id is not None else None
    except (TypeError, ValueError):
        equipment_id = None
    return rca_constraints(
        diagnosis_status=conclusion.get("diagnosis_status"),
        reliable_root_cause=bool(conclusion.get("reliable_root_cause")),
        equipment_id=equipment_id,
        equipment_type=_equipment_type_for(trusted, equipment_id),
        supported_hypothesis_ids=conclusion.get("supported_hypothesis_ids") or [],
    )


def _investigation_recommendation_text(session: Session, ctx: OperationalContext, alert: Any) -> str | None:
    try:
        rows = find_investigations(
            session,
            site_id=ctx.site_id,
            source_record_id=f"alert-{alert.alert_id}",
            shift_id=ctx.shift_id,
        )
    except Exception:
        return None
    if not isinstance(rows, (list, tuple)) or not rows:
        return None
    recommendation = getattr(rows[0], "recommendation", None)
    if not isinstance(recommendation, dict):
        return None
    text = recommendation.get("description")
    return str(text).strip() if text else None


def create_optimization_workflow(
    session: Session,
    ctx: OperationalContext,
    alert_id: str,
    *,
    provider: LLMProvider | None = None,
) -> dict:
    """Advanced / experimental LLM planner + reviewer. Default Actions IA uses create_optimization_run."""
    alert = get_site_alert_or_404(session, ctx.site_id, alert_id)
    eligibility = eligibility_for_alert(alert)
    if eligibility == ELIG_NOT_APPLICABLE:
        return create_optimization_run(
            session,
            ctx,
            alert_id,
            extra_snapshot={
                "workflow": {
                    "workflowStatus": WorkflowStatus.DETERMINISTIC_ONLY.value,
                    "optimizationPassCount": 0,
                    "reoptimizationOccurred": False,
                    "orchestratorVersion": ORCHESTRATOR_VERSION,
                }
            },
        )

    settings = get_settings()
    semaphore = investigation_gate.semaphore(getattr(settings, "ai_investigation_max_concurrent", 2))
    with semaphore:
        return _run_orchestrated(session, ctx, alert, alert_id, provider=provider)


def _run_orchestrated(
    session: Session,
    ctx: OperationalContext,
    alert: Any,
    alert_id: str,
    *,
    provider: LLMProvider | None,
) -> dict:
    total_started = monotonic()
    timings: dict[str, int] = {}
    eligibility = eligibility_for_alert(alert)
    weather_status = None
    snapshot: dict[str, Any] = {
        "siteId": ctx.site_id,
        "shiftId": ctx.shift_id,
        "simNow": ctx.sim_now.isoformat() if ctx.sim_now else None,
        "alertType": alert.alert_type,
        "eligibility": eligibility,
    }
    try:
        weather_started = monotonic()
        weather = get_weather_context(session, ctx.site_id)
        timings["weather_ms"] = _ms(weather_started)
        weather_status = weather.status.value
        snapshot["weather"] = {
            "status": weather_status,
            "unavailableReason": weather.unavailableReason,
            "condition": weather.current.condition if weather.current else None,
        }
    except Exception:
        timings.setdefault("weather_ms", 0)
        logger.exception("workflow weather lookup failed")

    trusted_started = monotonic()
    trusted = build_trusted_optimization_input(session, ctx, alert)
    rca = _rca_from_investigation(session, ctx, alert, trusted)
    timings["trusted_input_ms"] = _ms(trusted_started)
    snapshot.update(trusted.snapshot_fields)
    if rca.hard_exclude_loader_ids:
        trusted.mechanical_risk_loader_ids = set(trusted.mechanical_risk_loader_ids) | set(rca.hard_exclude_loader_ids)
    if rca.evidence_ids:
        facts_ids = list(trusted.planner_facts.get("evidenceIds") or [])
        facts_ids.extend(item for item in rca.evidence_ids if item not in facts_ids)
        trusted.planner_facts["evidenceIds"] = facts_ids[:40]
    facts = trusted.planner_facts
    llm = provider
    planner_failed = False
    planner_decision: OptimizationPlannerDecision | None = None
    planner_rejected: list[str] = []
    planner_meta = _provider_meta(llm)
    try:
        planner_started = monotonic()
        if llm is None:
            llm = create_llm_provider()
        payload = planner_payload_from_facts(facts)
        raw_decision = llm.plan_optimization(payload)
        planner_decision, planner_rejected = sanitize_planner_decision(raw_decision, facts=facts)
        planner_meta = _provider_meta(llm)
        timings["planner_ms"] = _ms(planner_started)
    except (LLMProviderError, Exception) as exc:
        timings["planner_ms"] = _ms(planner_started) if "planner_started" in locals() else 0
        if isinstance(exc, HTTPException):
            raise
        logger.exception("optimization planner failed alert_id=%s", alert_id)
        planner_failed = True
        planner_meta = _provider_meta(llm)

    if planner_failed or planner_decision is None:
        timings["optimization_total_ms"] = _ms(total_started)
        logger.info(
            "optimization workflow timings alert_id=%s outcome=DETERMINISTIC_ONLY timings=%s",
            alert_id,
            timings,
        )
        return create_optimization_run(
            session,
            ctx,
            alert_id,
            extra_snapshot={
                "workflow": {
                    "workflowStatus": WorkflowStatus.DETERMINISTIC_ONLY.value,
                    "optimizationPassCount": 0,
                    "reoptimizationOccurred": False,
                    "orchestratorVersion": ORCHESTRATOR_VERSION,
                    "planner": {**planner_meta, "failed": True},
                    "operatorSummary": DETERMINISTIC_ONLY_COPY,
                    "timings": timings,
                },
                "timings": timings,
            },
        )

    optimizer_ids = list(planner_decision.selected_optimizers)
    objectives = list(planner_decision.objectives)
    constraints = list(planner_decision.requested_constraint_checks)
    if rca.hard_exclude_loader_ids and ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK not in constraints:
        constraints.append(ConstraintCode.EXCLUDE_CRITICAL_MECHANICAL_RISK)
    rejected_codes = list(planner_rejected)
    engine_dict = trusted.as_engine_dict()
    candidates: list[dict] = []
    review: OptimizationReview | None = None
    review_status: ReviewStatus | None = None
    review_failed = False
    review_meta: dict[str, Any] = {}
    reoptimization_occurred = False
    pass_count = 0

    for optimization_pass in range(MAX_OPTIMIZATION_PASSES):
        pass_count = optimization_pass + 1
        if trusted.truck is None or trusted.dest_code is None:
            candidates = []
            break
        engine_started = monotonic()
        candidates = execute_selected_engines(
            trusted=engine_dict,
            optimizer_ids=optimizer_ids,
            objectives=objectives,
            constraints=constraints,
        )
        candidates = apply_rca_excludes(candidates, rca.hard_exclude_loader_ids)
        timings[f"engine_pass_{pass_count}_ms"] = _ms(engine_started)
        if not _can_spend_llm(llm):
            review_failed = True
            review = None
            review_status = None
            review_meta = {**_provider_meta(llm), "skipped": "budget_too_small"}
            break
        try:
            if llm is None:
                raise LLMProviderError("reviewer provider missing")
            review_started = monotonic()
            raw_review = llm.review_optimization(
                {
                    "optimization_pass": optimization_pass,
                    "alertType": facts.get("alertType"),
                    "planner": _dump(planner_decision),
                    "optimizerIds": [item.value for item in optimizer_ids],
                    "objectives": [item.value for item in objectives],
                    "appliedConstraintCodes": [item.value for item in constraints],
                    "evidenceIds": facts.get("evidenceIds") or [],
                    "hasMechanicalRiskAlert": facts.get("hasMechanicalRiskAlert"),
                    "candidates": _candidate_review_payload(candidates),
                }
            )
            review, extra_rejected = sanitize_review(
                raw_review,
                candidate_ids=[row["candidateId"] for row in candidates],
                known_evidence_ids=list(facts.get("evidenceIds") or []),
                optimization_pass=optimization_pass,
                allowed_constraints=list(ConstraintCode),
            )
            rejected_codes.extend(extra_rejected)
            review_status = review.status
            review_meta = _provider_meta(llm)
            timings[f"reviewer_pass_{pass_count}_ms"] = _ms(review_started)
        except (LLMProviderError, Exception) as exc:
            timings[f"reviewer_pass_{pass_count}_ms"] = _ms(review_started) if "review_started" in locals() else 0
            if isinstance(exc, HTTPException):
                raise
            logger.exception("optimization reviewer failed alert_id=%s pass=%s", alert_id, optimization_pass)
            review_failed = True
            review = None
            review_status = None
            review_meta = _provider_meta(llm)
            break

        if review_status == ReviewStatus.INSUFFICIENT_EVIDENCE:
            break
        if review_status == ReviewStatus.REOPTIMIZE and optimization_pass == 0:
            if not _can_spend_llm(llm):
                review_failed = True
                review_meta = {**review_meta, "skipped": "budget_too_small"}
                break
            reoptimization_occurred = True
            extra_constraints = list(review.requested_constraint_checks) if review else []
            extra_engines = list(review.requested_optimizer_ids) if review else []
            for item in extra_engines:
                if item not in optimizer_ids and len(optimizer_ids) < 2:
                    optimizer_ids.append(item)
            for item in extra_constraints:
                if item not in constraints:
                    constraints.append(item)
            continue
        break

    outcome, missing_reason = dispatch_outcome(
        truck=trusted.truck, dest=trusted.dest_code, candidates=candidates
    )
    if review_status == ReviewStatus.INSUFFICIENT_EVIDENCE:
        finalized = finalize_recommendations(
            candidates,
            preferred_ids=[],
            review_status=review_status,
            objectives=objectives,
        )
        workflow_status = WorkflowStatus.INSUFFICIENT_EVIDENCE
        operator_summary = (review.operator_summary if review and review.operator_summary else None) or (
            "Preuves insuffisantes pour recommander un changement de plan."
        )
        caution = review.caution_summary if review else None
        recommended = finalized["baselineCandidateId"]
        displayed_ids: list[str] = []
        stamped = finalized["candidates"]
    else:
        preferred = list(review.preferred_candidate_ids) if review else []
        finalized = finalize_recommendations(
            candidates,
            preferred_ids=preferred,
            review_status=review_status,
            objectives=objectives,
        )
        stamped = finalized["candidates"]
        displayed_ids = list(finalized["displayedCandidateIds"])
        recommended = finalized["recommendedCandidateId"]
        if review_failed:
            workflow_status = WorkflowStatus.REVIEW_UNAVAILABLE
            operator_summary = REVIEW_UNAVAILABLE_COPY
            caution = None
        elif finalized["workflowStatus"] == WorkflowStatus.NO_CHANGE_RECOMMENDED.value:
            if outcome == FEASIBLE:
                workflow_status = WorkflowStatus.NO_CHANGE_RECOMMENDED
                operator_summary = NO_CHANGE_OPERATOR_COPY
                caution = review.caution_summary if review else None
            else:
                workflow_status = WorkflowStatus.ORCHESTRATED if not review_failed else WorkflowStatus.REVIEW_UNAVAILABLE
                operator_summary = REVIEW_UNAVAILABLE_COPY if review_failed else (review.operator_summary if review else None)
                caution = review.caution_summary if review else None
        else:
            workflow_status = WorkflowStatus.ORCHESTRATED
            operator_summary = (review.operator_summary if review and review.operator_summary else None) or None
            caution = review.caution_summary if review else None

    if outcome == NOT_APPLICABLE:
        workflow_status = WorkflowStatus.DETERMINISTIC_ONLY

    rca_caution = "; ".join(rca.caution_notes) if rca.caution_notes else None
    if rca_caution:
        caution = f"{caution} {rca_caution}".strip() if caution else rca_caution

    explanation = explain_run(
        outcome=outcome,
        eligibility=eligibility,
        candidates=stamped,
        weights=dict(DEFAULT_WEIGHTS),
        weather_status=weather_status,
        missing_reason=missing_reason,
    )
    if workflow_status == WorkflowStatus.NO_CHANGE_RECOMMENDED and outcome == FEASIBLE:
        explanation["why"] = NO_CHANGE_OPERATOR_COPY
        explanation["recommendedCandidateId"] = finalized["baselineCandidateId"]
        recommended = finalized["baselineCandidateId"]
    elif workflow_status == WorkflowStatus.REVIEW_UNAVAILABLE:
        explanation["why"] = REVIEW_UNAVAILABLE_COPY
    elif operator_summary and outcome == FEASIBLE:
        explanation["why"] = operator_summary
    if displayed_ids:
        explanation["recommendedCandidateId"] = displayed_ids[0]
        recommended = displayed_ids[0]

    versions = {item.value: get_spec(item).version for item in optimizer_ids}
    snapshot["workflow"] = {
        "workflowStatus": workflow_status.value,
        "reviewStatus": review_status.value if review_status else None,
        "optimizationPassCount": pass_count,
        "reoptimizationOccurred": reoptimization_occurred,
        "orchestratorVersion": ORCHESTRATOR_VERSION,
        "planner": {
            **planner_meta,
            "failed": False,
            "decision": _dump(planner_decision),
            "rejected": planner_rejected,
        },
        "optimizerIds": [item.value for item in optimizer_ids],
        "optimizerVersions": versions,
        "objectives": [item.value for item in objectives],
        "appliedConstraintCodes": [item.value for item in constraints],
        "rejectedConstraintCodes": rejected_codes,
        "baselineCandidateId": finalized["baselineCandidateId"],
        "displayedCandidateIds": displayed_ids,
        "review": _dump(review) if review else None,
        "reviewer": {**review_meta, "failed": review_failed} if review_meta or review_failed else None,
        "operatorSummary": operator_summary,
        "cautionSummary": caution,
        "rcaGate": {
            "hardExcludeLoaderIds": sorted(rca.hard_exclude_loader_ids),
            "cautionNotes": list(rca.caution_notes),
            "evidenceIds": list(rca.evidence_ids),
        },
        "operatorRecommendedAction": compose_operator_recommended_action(
            eligibility=eligibility,
            outcome=outcome,
            operator_summary=operator_summary,
            recommended=next((row for row in stamped if row.get("candidateId") == recommended), None),
            investigation_description=_investigation_recommendation_text(session, ctx, alert),
            workflow_status=workflow_status.value,
        ),
        "weights": dict(DEFAULT_WEIGHTS),
        "timings": timings,
    }
    persist_started = monotonic()
    persisted = persist_evaluated_run(
        session,
        ctx,
        alert_id=alert.alert_id,
        eligibility=eligibility,
        outcome=outcome,
        candidates=stamped,
        recommended_candidate_id=recommended,
        weather_status=weather_status,
        snapshot=snapshot,
        weights=dict(DEFAULT_WEIGHTS),
        explanation=explanation,
    )
    timings["persist_ms"] = _ms(persist_started)
    timings["optimization_total_ms"] = _ms(total_started)
    snapshot["workflow"]["timings"] = timings
    snapshot["timings"] = timings
    logger.info(
        "optimization workflow timings alert_id=%s outcome=%s workflow=%s timings=%s",
        alert_id,
        outcome,
        workflow_status.value,
        timings,
    )
    if isinstance(persisted, dict):
        persisted = {**persisted, "snapshot": snapshot}
    return persisted


def format_optimization_timeline(snapshot: dict[str, Any] | None) -> str:
    """Compact developer timeline. Never includes prompts, keys, or chain-of-thought."""
    data = snapshot or {}
    workflow = data.get("workflow") if isinstance(data.get("workflow"), dict) else {}
    timings = workflow.get("timings") if isinstance(workflow.get("timings"), dict) else data.get("timings") or {}
    planner = workflow.get("planner") if isinstance(workflow.get("planner"), dict) else {}
    reviewer = workflow.get("reviewer") if isinstance(workflow.get("reviewer"), dict) else {}
    lines = [
        "=== Optimization workflow ===",
        (
            f"total_ms={timings.get('optimization_total_ms')} "
            f"planner_ms={timings.get('planner_ms')} "
            f"reviewer_ms={timings.get('reviewer_pass_1_ms')} "
            f"engine_ms={timings.get('engine_pass_1_ms')} "
            f"persist_ms={timings.get('persist_ms')}"
        ),
        f"planner provider={planner.get('provider') or planner.get('finalProvider')} fallback={planner.get('fallbackOccurred')}",
        f"reviewer provider={reviewer.get('provider') or reviewer.get('finalProvider')} failed={reviewer.get('failed')} skipped={reviewer.get('skipped')}",
        f"workflowStatus={workflow.get('workflowStatus')} passes={workflow.get('optimizationPassCount')}",
    ]
    for key in (
        "weather_ms",
        "trusted_input_ms",
        "planner_ms",
        "engine_pass_1_ms",
        "reviewer_pass_1_ms",
        "engine_pass_2_ms",
        "reviewer_pass_2_ms",
        "persist_ms",
    ):
        if key in timings:
            lines.append(f"  {key:<22} {timings[key]:>8}ms")
    return "\n".join(lines).rstrip() + "\n"
