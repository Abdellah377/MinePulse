"""Application entry point for invoking one investigation graph run."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import (
    InvestigationResult,
    InvestigationTrigger,
    ResolvedOperationalContext,
)
from app.ai.graph import build_investigation_graph, initial_state
from app.ai.llm.provider import LLMProvider, create_llm_provider
from app.ai.nodes import InvestigationRuntime
from app.ai.persistence import state_to_result
from app.ai.state import InvestigationState
from app.ai.tools import EvidenceToolRegistry
from app.config import get_settings
from app.db.models import Equipment, Shift, Site, Zone
from app.services.operational.context import OperationalContext, get_operational_context


def validate_trigger_scope(session: Session, trigger: InvestigationTrigger) -> Site:
    site = session.get(Site, trigger.site_id)
    if site is None or not site.active:
        raise HTTPException(status_code=404, detail=f"Active site not found: {trigger.site_id}")
    if trigger.equipment_id is not None:
        equipment = session.scalar(
            select(Equipment.equipment_id).where(
                Equipment.equipment_id == trigger.equipment_id,
                Equipment.site_id == trigger.site_id,
            )
        )
        if equipment is None:
            raise HTTPException(status_code=404, detail="Equipment not found at trigger site")
    if trigger.zone_id is not None:
        zone = session.scalar(
            select(Zone.zone_id).where(
                Zone.zone_id == trigger.zone_id,
                Zone.site_id == trigger.site_id,
            )
        )
        if zone is None:
            raise HTTPException(status_code=404, detail="Zone not found at trigger site")
    return site


def resolve_trigger_context(session: Session, trigger: InvestigationTrigger) -> OperationalContext:
    site = validate_trigger_scope(session, trigger)
    return get_operational_context(
        session,
        site_code=site.code,
        shift_id=trigger.shift_id,
    )


def reconstruct_operational_context(
    session: Session,
    serialized: ResolvedOperationalContext,
) -> OperationalContext:
    """Rebuild ORM-backed service context solely from serializable graph state."""
    site = session.get(Site, serialized.site_id)
    if site is None:
        raise RuntimeError(f"Investigation site no longer exists: {serialized.site_id}")
    shift = session.get(Shift, serialized.shift_id) if serialized.shift_id is not None else None
    if shift is not None and shift.site_id != serialized.site_id:
        raise RuntimeError("Investigation shift no longer belongs to the resolved site")
    if serialized.shift_id is not None and shift is None:
        raise RuntimeError(f"Investigation shift no longer exists: {serialized.shift_id}")
    return OperationalContext(
        site=site,
        shift=shift,
        sim_now=serialized.operational_now,
        shift_window_start=serialized.window_start,
        shift_window_end=serialized.window_end,
    )


def run_investigation(
    session: Session,
    trigger: InvestigationTrigger,
    *,
    provider: LLMProvider | None = None,
    max_iterations: int | None = None,
) -> InvestigationResult:
    settings = get_settings()
    llm = provider or create_llm_provider(settings)
    rounds = max_iterations or settings.ai_max_investigation_iterations
    if rounds < 1:
        raise ValueError("max_iterations must be at least 1")
    # Validate before graph creation so invalid foreign-key scope cannot produce
    # an unpersistable failed investigation record.
    validate_trigger_scope(session, trigger)
    runtime = InvestigationRuntime(
        session=session,
        provider=llm,
        tools=EvidenceToolRegistry(session),
        context_resolver=resolve_trigger_context,
        context_reconstructor=reconstruct_operational_context,
    )
    graph = build_investigation_graph(runtime)
    state = initial_state(
        trigger,
        max_iterations=rounds,
        provider=llm.provider_name,
        model=llm.model_name,
    )
    result: InvestigationState = graph.invoke(
        state,
        config={"recursion_limit": max(25, rounds * 4 + 10)},
    )
    return state_to_result(result)
