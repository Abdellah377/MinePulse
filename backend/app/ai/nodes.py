"""Investigation node implementations with injected operational and LLM boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.contracts import (
    ConfidenceLevel,
    Contradiction,
    DiagnosisResult,
    EvidenceKind,
    EvidenceRequestType,
    Hypothesis,
    InvestigationConclusion,
    InvestigationError,
    InvestigationRecommendation,
    InvestigationStatus,
    InvestigationTrigger,
    ResolvedOperationalContext,
)
from app.ai.llm.provider import LLMProvider
from app.ai.persistence import persist_investigation
from app.ai.state import InvestigationState
from app.ai.tools import EvidenceToolRegistry
from app.services.operational.context import OperationalContext


@dataclass
class InvestigationRuntime:
    session: Session
    provider: LLMProvider
    tools: EvidenceToolRegistry
    context_resolver: Callable[[Session, InvestigationTrigger], OperationalContext]
    persister: Callable[[Session, InvestigationState], object] = persist_investigation
    operational_context: OperationalContext | None = field(default=None, init=False)


def _error(stage: str, exc: Exception) -> dict:
    return {
        "status": InvestigationStatus.FAILED,
        "error": InvestigationError(
            stage=stage,
            error_type=type(exc).__name__,
            message=str(exc),
        ),
    }


def _json(value):
    if value is None:
        return None
    if isinstance(value, list):
        return [item.model_dump(mode="json") for item in value]
    return value.model_dump(mode="json")


class InvestigationNodes:
    def __init__(self, runtime: InvestigationRuntime):
        self.runtime = runtime

    def resolve_context(self, state: InvestigationState) -> dict:
        try:
            ctx = self.runtime.context_resolver(self.runtime.session, state["trigger"])
            self.runtime.operational_context = ctx
            resolved = ResolvedOperationalContext(
                site_id=ctx.site_id,
                site_code=ctx.site_code,
                site_name=ctx.site.name,
                shift_id=ctx.shift_id,
                shift_name=ctx.shift.name if ctx.shift else None,
                operational_now=ctx.sim_now,
                window_start=ctx.shift_window_start,
                window_end=ctx.shift_window_end,
            )
            return {
                "operational_context": resolved,
                "status": InvestigationStatus.GATHERING_EVIDENCE,
            }
        except Exception as exc:
            return _error("resolve_context", exc)

    def gather_initial_evidence(self, state: InvestigationState) -> dict:
        ctx = self.runtime.operational_context
        if ctx is None:
            return _error("gather_initial_evidence", RuntimeError("Operational context was not resolved"))
        evidence = self.runtime.tools.gather_initial(ctx, state["trigger"])
        return {
            "evidence": evidence,
            "status": InvestigationStatus.ANALYZING,
        }

    def analyze(self, state: InvestigationState) -> dict:
        next_iteration = state["iteration_count"] + 1
        payload = {
            "trigger": _json(state["trigger"]),
            "operationalContext": _json(state["operational_context"]),
            "evidence": _json(state["evidence"]),
            "investigationRound": next_iteration,
            "maxInvestigationRounds": state["max_iterations"],
            "approvedEvidenceRequestTypes": [item.value for item in EvidenceRequestType],
        }
        try:
            diagnosis = self.runtime.provider.diagnose(payload)
            diagnosis = self._sanitize_diagnosis(diagnosis, state)
        except Exception as exc:
            return {"iteration_count": next_iteration, **_error("analyze", exc)}
        limit_reached = bool(
            diagnosis.requested_information and next_iteration >= state["max_iterations"]
        )
        return {
            "diagnosis": diagnosis,
            "hypotheses": diagnosis.hypotheses,
            "requested_information": diagnosis.requested_information,
            "contradictions": diagnosis.contradictions,
            "iteration_count": next_iteration,
            "iteration_limit_reached": limit_reached,
            "status": InvestigationStatus.ANALYZING,
        }

    def gather_requested_evidence(self, state: InvestigationState) -> dict:
        ctx = self.runtime.operational_context
        if ctx is None:
            return _error(
                "gather_requested_evidence", RuntimeError("Operational context was not resolved")
            )
        additional = self.runtime.tools.gather_requested(ctx, state["requested_information"])
        return {
            "evidence": [*state["evidence"], *additional],
            "status": InvestigationStatus.ANALYZING,
        }

    def build_conclusion(self, state: InvestigationState) -> dict:
        payload = {
            "trigger": _json(state["trigger"]),
            "operationalContext": _json(state["operational_context"]),
            "evidence": _json(state["evidence"]),
            "diagnosis": _json(state["diagnosis"]),
            "iterationLimitReached": state["iteration_limit_reached"],
        }
        try:
            conclusion = self.runtime.provider.build_conclusion(payload)
            conclusion = self._sanitize_conclusion(conclusion, state)
        except Exception as exc:
            return _error("build_conclusion", exc)
        return {
            "conclusion": conclusion,
            "status": InvestigationStatus.BUILDING_RECOMMENDATION,
        }

    def build_recommendation(self, state: InvestigationState) -> dict:
        payload = {
            "trigger": _json(state["trigger"]),
            "conclusion": _json(state["conclusion"]),
            "evidence": _json(state["evidence"]),
            "allowedActions": [
                "INSPECT_EQUIPMENT",
                "VERIFY_OPERATIONAL_CONDITION",
                "REVIEW_QUEUE_DISTRIBUTION",
                "ESCALATE_TO_MAINTENANCE",
                "CONSIDER_REASSIGNMENT",
                "CONTINUE_MONITORING",
                "NO_ACTION",
            ],
        }
        try:
            recommendation = self.runtime.provider.build_recommendation(payload)
            valid_evidence = {
                item.evidence_id for item in state["evidence"] if item.available
            }
            valid_equipment_ids, valid_zone_ids = self._evidence_entity_ids(state)
            recommendation = recommendation.model_copy(
                update={
                    "evidence_ids": [
                        item for item in recommendation.evidence_ids if item in valid_evidence
                    ],
                    "target_equipment_id": (
                        recommendation.target_equipment_id
                        if recommendation.target_equipment_id in valid_equipment_ids
                        else None
                    ),
                    "target_zone_id": (
                        recommendation.target_zone_id
                        if recommendation.target_zone_id in valid_zone_ids
                        else None
                    ),
                    "human_validation_required": True,
                }
            )
        except Exception as exc:
            return _error("build_recommendation", exc)
        conclusion = state["conclusion"]
        uncertain = bool(
            state["iteration_limit_reached"]
            or conclusion is None
            or not conclusion.reliable_root_cause
            or conclusion.unresolved_uncertainties
        )
        return {
            "recommendation": recommendation,
            "status": (
                InvestigationStatus.COMPLETED_WITH_UNCERTAINTY
                if uncertain
                else InvestigationStatus.COMPLETED
            ),
            "completed_at": datetime.now(timezone.utc),
        }

    def persist(self, state: InvestigationState) -> dict:
        completed_at = state["completed_at"] or datetime.now(timezone.utc)
        final_state = {**state, "completed_at": completed_at}
        self.runtime.persister(self.runtime.session, final_state)
        return {"completed_at": completed_at}

    @staticmethod
    def _sanitize_diagnosis(
        diagnosis: DiagnosisResult,
        state: InvestigationState,
    ) -> DiagnosisResult:
        valid_evidence = {
            item.evidence_id for item in state["evidence"] if item.available
        }
        hypotheses = []
        for hypothesis in diagnosis.hypotheses:
            supporting = [item for item in hypothesis.supporting_evidence_ids if item in valid_evidence]
            contradictory = [
                item for item in hypothesis.contradictory_evidence_ids if item in valid_evidence
            ]
            confidence = hypothesis.confidence if supporting else ConfidenceLevel.LOW
            hypotheses.append(
                hypothesis.model_copy(
                    update={
                        "supporting_evidence_ids": supporting,
                        "contradictory_evidence_ids": contradictory,
                        "confidence": confidence,
                    }
                )
            )
        contradictions: list[Contradiction] = []
        for contradiction in diagnosis.contradictions:
            ids = list(dict.fromkeys(i for i in contradiction.evidence_ids if i in valid_evidence))
            if len(ids) >= 2:
                contradictions.append(contradiction.model_copy(update={"evidence_ids": ids}))
        return diagnosis.model_copy(
            update={"hypotheses": hypotheses, "contradictions": contradictions}
        )

    @staticmethod
    def _sanitize_conclusion(
        conclusion: InvestigationConclusion,
        state: InvestigationState,
    ) -> InvestigationConclusion:
        fact_ids = {
            item.evidence_id
            for item in state["evidence"]
            if item.available and item.kind == EvidenceKind.FACT
        }
        metric_ids = {
            item.evidence_id
            for item in state["evidence"]
            if item.available
            and item.kind in {EvidenceKind.DERIVED_METRIC, EvidenceKind.MODEL_PREDICTION}
        }
        hypothesis_ids = {item.hypothesis_id for item in state["hypotheses"]}
        updates = {
            "observed_fact_evidence_ids": [
                item for item in conclusion.observed_fact_evidence_ids if item in fact_ids
            ],
            "derived_metric_evidence_ids": [
                item for item in conclusion.derived_metric_evidence_ids if item in metric_ids
            ],
            "supported_hypothesis_ids": [
                item for item in conclusion.supported_hypothesis_ids if item in hypothesis_ids
            ],
        }
        if state["iteration_limit_reached"]:
            uncertainties = list(conclusion.unresolved_uncertainties)
            uncertainties.extend(req.reason for req in state["requested_information"])
            updates.update(
                {
                    "summary": (
                        "Available evidence is insufficient to determine a reliable root cause. "
                        + conclusion.summary
                    ),
                    "root_cause": None,
                    "reliable_root_cause": False,
                    "confidence": ConfidenceLevel.LOW,
                    "unresolved_uncertainties": list(dict.fromkeys(uncertainties)),
                }
            )
        elif conclusion.root_cause is None:
            updates["reliable_root_cause"] = False
        return conclusion.model_copy(update=updates)

    @staticmethod
    def _evidence_entity_ids(state: InvestigationState) -> tuple[set[int], set[int]]:
        equipment_ids = {
            item.equipment_id
            for item in state["evidence"]
            if item.available and item.equipment_id is not None
        }
        zone_ids = {
            item.zone_id
            for item in state["evidence"]
            if item.available and item.zone_id is not None
        }
        trigger = state["trigger"]
        if trigger.equipment_id is not None:
            equipment_ids.add(trigger.equipment_id)
        if trigger.zone_id is not None:
            zone_ids.add(trigger.zone_id)

        def visit(value) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(item, int) and key in {"equipmentId", "truckId", "loaderId"}:
                        equipment_ids.add(item)
                    elif isinstance(item, int) and key in {
                        "zoneId",
                        "originZoneId",
                        "destinationZoneId",
                    }:
                        zone_ids.add(item)
                    else:
                        visit(item)

        for evidence in state["evidence"]:
            if evidence.available:
                visit(evidence.value)
        return equipment_ids, zone_ids
