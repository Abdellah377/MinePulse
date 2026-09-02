"""Application entry point for invoking one investigation graph run."""

from __future__ import annotations

import logging
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTrigger,
    ResolvedOperationalContext,
)
from app.ai.debug import DebugEventType, create_debug_recorder
from app.ai.graph import build_investigation_graph, initial_state
from app.ai.lifecycle import investigation_gate, latest_investigation, reusable_investigation
from app.ai.llm.provider import LLMProvider, create_llm_provider
from app.ai.nodes import InvestigationRuntime
from app.ai.persistence import state_to_result, verify_investigation_storage
from app.ai.state import InvestigationState
from app.ai.tools import EvidenceToolRegistry
from app.config import get_settings
from app.db.models import Equipment, Shift, Site, Zone
from app.services.operational.context import OperationalContext, get_operational_context

logger = logging.getLogger(__name__)


def validate_trigger_scope(session: Session, trigger: InvestigationTrigger) -> Site:
    site = session.get(Site, trigger.site_id)
    if site is None or not site.active:
        raise HTTPException(status_code=404, detail=f"Active site not found: {trigger.site_id}")
    if trigger.shift_id is not None:
        shift = session.get(Shift, trigger.shift_id)
        if shift is None or shift.site_id != trigger.site_id:
            raise HTTPException(status_code=404, detail="Shift not found at trigger site")
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
    verify_investigation_storage(session)
    rounds = max_iterations or settings.ai_max_investigation_iterations
    if rounds < 1:
        raise ValueError("max_iterations must be at least 1")
    # Validate before graph creation so invalid foreign-key scope cannot produce
    # an unpersistable failed investigation record.
    validate_trigger_scope(session, trigger)
    lock = investigation_gate.scope_lock(trigger.site_id, trigger.source_record_id)
    with lock:
        existing = latest_investigation(session, trigger)
        reused = reusable_investigation(existing)
        if reused is not None:
            logger.info(
                "Investigation reused without a new provider run",
                extra={
                    "investigation_id": str(reused.investigation_id),
                    "alert_id": trigger.source_record_id,
                    "trigger_source": trigger.trigger_source.value,
                    "status": reused.status.value,
                },
            )
            return reused
        llm = provider or create_llm_provider(settings)
        semaphore = investigation_gate.semaphore(getattr(settings, "ai_investigation_max_concurrent", 2))
        with semaphore:
            investigation_gate.mark_enter()
            started = monotonic()
            category = "success"
            investigation_id = ""
            try:
                mapped = _invoke_investigation_graph(
                    session,
                    trigger,
                    llm=llm,
                    rounds=rounds,
                    debug_enabled=settings.ai_debug_mode,
                )
                investigation_id = str(mapped.investigation_id)
                if mapped.status == InvestigationStatus.FAILED and mapped.error is not None:
                    category = mapped.error.error_type
                return mapped
            except Exception as exc:
                category = type(exc).__name__
                raise
            finally:
                investigation_gate.mark_leave()
                logger.info(
                    "Investigation invocation finished",
                    extra={
                        "investigation_id": investigation_id,
                        "alert_id": trigger.source_record_id,
                        "trigger_source": trigger.trigger_source.value,
                        "failure_category": category,
                        "duration_ms": int((monotonic() - started) * 1000),
                        "max_concurrent": settings.ai_investigation_max_concurrent,
                    },
                )


def _invoke_investigation_graph(
    session: Session,
    trigger: InvestigationTrigger,
    *,
    llm: LLMProvider,
    rounds: int,
    debug_enabled: bool,
) -> InvestigationResult:
    state = initial_state(
        trigger,
        max_iterations=rounds,
        provider=llm.provider_name,
        model=llm.model_name,
    )
    debug = create_debug_recorder(
        enabled=debug_enabled,
        investigation_id=state["investigation_id"],
        model=llm.model_name,
    )
    debug.record(
        DebugEventType.INVESTIGATION_STARTED,
        stage="run_investigation",
        summary="Investigation started",
        metadata={
            "trigger_type": trigger.trigger_type.value,
            "trigger_source": trigger.trigger_source.value,
            "max_iterations": rounds,
            "provider": llm.provider_name,
            "model": llm.model_name,
            "alert_id": trigger.source_record_id,
        },
    )
    logger.info(
        "Investigation requested",
        extra={
            "investigation_id": state["investigation_id"],
            "alert_id": trigger.source_record_id,
            "trigger_source": trigger.trigger_source.value,
            "trigger_type": trigger.trigger_type.value,
            "provider": llm.provider_name,
        },
    )
    runtime = InvestigationRuntime(
        session=session,
        provider=llm,
        tools=EvidenceToolRegistry(session, debug=debug),
        context_resolver=resolve_trigger_context,
        context_reconstructor=reconstruct_operational_context,
        debug=debug,
    )
    graph = build_investigation_graph(runtime)
    result: InvestigationState = graph.invoke(
        state,
        config={"recursion_limit": max(25, rounds * 4 + 10)},
    )
    mapped = state_to_result(result)
    category = "success"
    if mapped.status == InvestigationStatus.FAILED and mapped.error is not None:
        category = mapped.error.error_type
    logger.info(
        "Investigation persisted",
        extra={
            "investigation_id": str(mapped.investigation_id),
            "alert_id": trigger.source_record_id,
            "trigger_source": trigger.trigger_source.value,
            "status": mapped.status.value,
            "failure_category": category,
            "evidence_count": len(mapped.evidence),
        },
    )
    return mapped
