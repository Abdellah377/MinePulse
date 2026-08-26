"""Durable investigation audit persistence, separate from graph working state."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import (
    Contradiction,
    EvidenceItem,
    EvidenceRequest,
    EvidenceRequestAttempt,
    Hypothesis,
    InvestigationConclusion,
    InvestigationError,
    InvestigationRecommendation,
    InvestigationResult,
    InvestigationStatus,
    InvestigationTrigger,
    ResolvedOperationalContext,
)
from app.ai.state import InvestigationState
from app.db.models import AiInvestigation


class InvestigationPersistenceError(RuntimeError):
    """The final investigation could not be durably stored."""


def verify_investigation_storage(session: Session) -> None:
    """Detect missing migrations/columns before spending a provider call."""
    session.execute(select(AiInvestigation).limit(0))


def _dump(value):
    if value is None:
        return None
    if isinstance(value, list):
        return [item.model_dump(mode="json") for item in value]
    return value.model_dump(mode="json")


def persist_investigation(session: Session, state: InvestigationState) -> AiInvestigation:
    investigation_id = UUID(state["investigation_id"])
    now = datetime.now(timezone.utc)
    row = session.get(AiInvestigation, investigation_id)
    if row is None:
        row = AiInvestigation(
            investigation_id=investigation_id,
            created_at=state["started_at"],
            updated_at=now,
            status=state["status"].value,
            trigger_type=state["trigger"].trigger_type.value,
            trigger_source=state["trigger"].trigger_source.value,
            site_id=state["trigger"].site_id,
            max_iterations=state["max_iterations"],
            graph_version=state["graph_version"],
            provider=state["provider"],
            model=state["model"],
            trigger_data={},
        )
        session.add(row)
    trigger = state["trigger"]
    row.updated_at = now
    row.completed_at = state["completed_at"]
    row.status = state["status"].value
    row.trigger_type = trigger.trigger_type.value
    row.trigger_source = trigger.trigger_source.value
    resolved = state["operational_context"]
    row.shift_id = resolved.shift_id if resolved is not None else trigger.shift_id
    row.equipment_id = trigger.equipment_id
    row.zone_id = trigger.zone_id
    row.iteration_count = state["iteration_count"]
    row.max_iterations = state["max_iterations"]
    row.graph_version = state["graph_version"]
    row.provider = state["provider"]
    row.model = state["model"]
    row.trigger_data = _dump(trigger)
    row.operational_context = _dump(state["operational_context"])
    row.evidence = _dump(state["evidence"])
    row.hypotheses = _dump(state["hypotheses"])
    row.requested_information = _dump(state["requested_information"])
    row.contradictions = _dump(state["contradictions"])
    row.conclusion = _dump(state["conclusion"])
    row.recommendation = _dump(state["recommendation"])
    row.error = _dump(state["error"])
    row.metadata_ = {
        "iterationLimitReached": state["iteration_limit_reached"],
        "evidenceExpansionExhausted": state["evidence_expansion_exhausted"],
        "evidenceRequestHistory": _dump(state["evidence_request_history"]),
    }
    session.commit()
    session.refresh(row)
    return row


def get_investigation(session: Session, investigation_id: UUID) -> AiInvestigation | None:
    return session.get(AiInvestigation, investigation_id)


def find_investigations(
    session: Session, *, site_id: int, source_record_id: str, shift_id: int | None = None
) -> list[AiInvestigation]:
    """Latest durable audit for an operational source, not a new investigation."""
    query = select(AiInvestigation).where(
        AiInvestigation.site_id == site_id,
        AiInvestigation.trigger_data["source_record_id"].as_string() == source_record_id,
    )
    if shift_id is not None:
        query = query.where(AiInvestigation.shift_id == shift_id)
    return list(session.scalars(query.order_by(
        AiInvestigation.created_at.desc(), AiInvestigation.investigation_id.desc()
    ).limit(1)).all())


def state_to_result(state: InvestigationState) -> InvestigationResult:
    return InvestigationResult(
        investigation_id=UUID(state["investigation_id"]),
        trigger=state["trigger"],
        operational_context=state["operational_context"],
        evidence=state["evidence"],
        hypotheses=state["hypotheses"],
        requested_information=state["requested_information"],
        evidence_request_history=state["evidence_request_history"],
        contradictions=state["contradictions"],
        conclusion=state["conclusion"],
        recommendation=state["recommendation"],
        iteration_count=state["iteration_count"],
        max_iterations=state["max_iterations"],
        iteration_limit_reached=state["iteration_limit_reached"],
        evidence_expansion_exhausted=state["evidence_expansion_exhausted"],
        status=state["status"],
        error=state["error"],
        started_at=state["started_at"],
        completed_at=state["completed_at"],
        graph_version=state["graph_version"],
        provider=state["provider"],
        model=state["model"],
    )


def record_to_result(row: AiInvestigation) -> InvestigationResult:
    meta = row.metadata_ or {}
    return InvestigationResult(
        investigation_id=row.investigation_id,
        trigger=InvestigationTrigger.model_validate(row.trigger_data),
        operational_context=(
            ResolvedOperationalContext.model_validate(row.operational_context)
            if row.operational_context
            else None
        ),
        evidence=[EvidenceItem.model_validate(item) for item in row.evidence or []],
        hypotheses=[Hypothesis.model_validate(item) for item in row.hypotheses or []],
        requested_information=[
            EvidenceRequest.model_validate(item) for item in row.requested_information or []
        ],
        evidence_request_history=[
            EvidenceRequestAttempt.model_validate(item)
            for item in meta.get("evidenceRequestHistory", [])
        ],
        contradictions=[Contradiction.model_validate(item) for item in row.contradictions or []],
        conclusion=(
            InvestigationConclusion.model_validate(row.conclusion) if row.conclusion else None
        ),
        recommendation=(
            InvestigationRecommendation.model_validate(row.recommendation)
            if row.recommendation
            else None
        ),
        iteration_count=row.iteration_count,
        max_iterations=row.max_iterations,
        iteration_limit_reached=bool(meta.get("iterationLimitReached", False)),
        evidence_expansion_exhausted=bool(meta.get("evidenceExpansionExhausted", False)),
        status=InvestigationStatus(row.status),
        error=InvestigationError.model_validate(row.error) if row.error else None,
        started_at=row.created_at,
        completed_at=row.completed_at,
        graph_version=row.graph_version,
        provider=row.provider,
        model=row.model,
    )
