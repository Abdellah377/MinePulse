"""Run real LangGraph investigations and score only their persisted results."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import InvestigationTrigger, TriggerSource
from app.ai.llm.provider import LLMProvider
from app.ai.persistence import get_investigation, record_to_result
from app.ai.service import run_investigation
from app.db.models import Equipment, Site
from app.services.operational.context import get_operational_context

from ai_eval.cases import get_case
from ai_eval.contracts import EvidenceTrace, EvaluationCase, EvaluationReport
from ai_eval.providers import DeterministicEvaluationProvider, MockProfile
from ai_eval.scoring import evaluate_result


def assert_ground_truth_isolated(
    case: EvaluationCase,
    trigger: InvestigationTrigger,
) -> None:
    """Fail closed if evaluator-only labels accidentally enter graph input."""
    serialized = trigger.model_dump_json().casefold()
    forbidden = {
        case.case_id.casefold(),
        case.ground_truth.label.value.casefold(),
        case.ground_truth.summary.casefold(),
    }
    if case.ground_truth.scenario_name:
        forbidden.add(case.ground_truth.scenario_name.casefold())
    if case.ground_truth.reviewer_notes:
        forbidden.add(case.ground_truth.reviewer_notes.casefold())
    leaked = sorted(value for value in forbidden if value and value in serialized)
    if leaked:
        raise RuntimeError("Evaluation ground truth leaked into investigation trigger")


def build_trigger(
    session: Session,
    case: EvaluationCase,
    *,
    site_code: str | None = None,
) -> InvestigationTrigger:
    """Resolve normal DB identifiers without exposing evaluation ground truth."""
    query = select(Equipment).where(Equipment.code == case.equipment_code, Equipment.active.is_(True))
    if site_code:
        query = query.join(Site).where(Site.code == site_code, Site.active.is_(True))
    equipment = session.scalar(query.order_by(Equipment.site_id, Equipment.equipment_id))
    if equipment is None:
        scope = f" at site {site_code}" if site_code else ""
        raise LookupError(f"Active equipment {case.equipment_code} not found{scope}")
    site = session.get(Site, equipment.site_id)
    if site is None or not site.active:
        raise LookupError(f"Active site for equipment {case.equipment_code} not found")
    context = get_operational_context(session, site_code=site.code)
    # Deliberately neutral payload: no case ID, scenario, expected cause, or evaluator notes.
    trigger = InvestigationTrigger(
        trigger_type=case.trigger_type,
        trigger_source=TriggerSource.USER_INVESTIGATE,
        source="ai-evaluation",
        source_record_id=f"ai-eval-{uuid4()}",
        site_id=context.site_id,
        shift_id=context.shift_id,
        equipment_id=equipment.equipment_id,
        occurred_at=context.sim_now,
        payload={"evaluation_run": True},
    )
    assert_ground_truth_isolated(case, trigger)
    return trigger


def default_mock_provider(case: EvaluationCase) -> DeterministicEvaluationProvider:
    if case.inconclusive_acceptable:
        profile = MockProfile.REQUEST_THEN_INCONCLUSIVE
        concept = "equipment stop"
    else:
        profile = MockProfile.REQUEST_MORE_EVIDENCE
        concept = (
            "communication loss"
            if case.trigger_type.value == "CONNECTIVITY_ISSUE"
            else "mechanical failure"
        )
    return DeterministicEvaluationProvider(
        profile=profile,
        concept=concept,
        request_type=case.mock_request_type,
    )


def report_from_result(
    case: EvaluationCase,
    trigger: InvestigationTrigger,
    result,
    *,
    reasoning_mode: str,
    persisted_ok: bool,
) -> EvaluationReport:
    checks, warnings, outcome = evaluate_result(case, result)
    reasoning_checks = [
        item for item in checks if item.category.value not in {"PIPELINE", "DATA_QUALITY"}
    ]
    return EvaluationReport(
        case_id=case.case_id,
        case_description=case.description,
        trigger=trigger,
        investigation_id=str(result.investigation_id),
        provider=result.provider,
        model=result.model,
        reasoning_mode=reasoning_mode,
        status=result.status.value,
        pipeline_correct=persisted_ok and result.error is None,
        reasoning_checks_passed=sum(item.passed for item in reasoning_checks),
        reasoning_checks_total=len(reasoning_checks),
        outcome=outcome,
        evidence=[
            EvidenceTrace(
                evidence_id=item.evidence_id,
                kind=item.kind,
                source_tool=item.source_tool,
                source_service=item.source_service,
                metric=item.metric,
                available=item.available,
                status=item.status.value if item.status else "UNKNOWN",
                source_record_ids=item.source_record_ids,
            )
            for item in result.evidence
        ],
        hypotheses=[item.model_dump(mode="json") for item in result.hypotheses],
        contradictions=[item.model_dump(mode="json") for item in result.contradictions],
        missing_information=[
            item.model_dump(mode="json") for item in result.requested_information
        ],
        evidence_request_history=[
            item.model_dump(mode="json") for item in result.evidence_request_history
        ],
        conclusion=(result.conclusion.model_dump(mode="json") if result.conclusion else None),
        root_cause_reliable=bool(
            result.conclusion and result.conclusion.reliable_root_cause
        ),
        recommendation=(
            result.recommendation.model_dump(mode="json")
            if result.recommendation
            else None
        ),
        iteration_count=result.iteration_count,
        checks=checks,
        data_quality_warnings=warnings,
        failure_stage=result.error.stage if result.error else None,
        human_review_notes=(
            case.ground_truth.reviewer_notes
            if reasoning_mode == "REAL_LLM"
            else "Mocked run validates pipeline behavior, not model diagnosis quality."
        ),
    )


def run_evaluation(
    session: Session,
    case: EvaluationCase | str,
    *,
    provider: LLMProvider | None = None,
    real_llm: bool = False,
    site_code: str | None = None,
    max_iterations: int | None = None,
) -> EvaluationReport:
    selected = get_case(case) if isinstance(case, str) else case
    trigger = build_trigger(session, selected, site_code=site_code)
    active_provider = provider
    if not real_llm and active_provider is None:
        active_provider = default_mock_provider(selected)
    result = run_investigation(
        session,
        trigger,
        provider=active_provider,
        max_iterations=max_iterations,
    )
    session.expire_all()
    record = get_investigation(session, result.investigation_id)
    if record is None:
        raise RuntimeError("Evaluation investigation was not durably persisted")
    persisted = record_to_result(record)
    if persisted != result:
        raise RuntimeError("Persisted investigation does not match graph result")
    return report_from_result(
        selected,
        trigger,
        persisted,
        reasoning_mode="REAL_LLM" if real_llm else "MOCKED_PIPELINE",
        persisted_ok=True,
    )
