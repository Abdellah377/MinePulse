"""Investigation node implementations with injected operational and LLM boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import traceback

from sqlalchemy.orm import Session

from app.ai.contracts import (
    ConfidenceLevel,
    ContributingFactor,
    Contradiction,
    DiagnosisStatus,
    DiagnosisResult,
    EvidenceKind,
    EvidenceRequest,
    EvidenceRequestAttempt,
    EvidenceRequestOutcome,
    EvidenceRequestType,
    EvidenceStatus,
    Hypothesis,
    InvestigationConclusion,
    InvestigationError,
    InvestigationRecommendation,
    InvestigationStatus,
    InvestigationTrigger,
    ResolvedOperationalContext,
    TelemetryMetricGroup,
)
from app.ai.causality import trigger_observation, validated_causal_depth
from app.ai.llm.provider import LLMProvider
from app.ai.persistence import InvestigationPersistenceError, persist_investigation
from app.ai.state import InvestigationState
from app.ai.tools import EvidenceToolRegistry
from app.services.operational.context import OperationalContext


@dataclass
class InvestigationRuntime:
    session: Session
    provider: LLMProvider
    tools: EvidenceToolRegistry
    context_resolver: Callable[[Session, InvestigationTrigger], OperationalContext]
    context_reconstructor: Callable[[Session, ResolvedOperationalContext], OperationalContext]
    persister: Callable[[Session, InvestigationState], object] = persist_investigation


logger = logging.getLogger(__name__)

_CONFIDENCE_RANK = {
    ConfidenceLevel.LOW: 0,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.HIGH: 2,
}
_TEMPORAL_KEYS = {
    "ts",
    "occurredAt",
    "startTime",
    "startedAt",
    "firstObservedAt",
    "lastObservedAt",
    "windowStart",
}
_OVERCONFIDENT_PHRASES = (
    "confirming",
    "confirmed diagnosis",
    "confirmed the",
    "confirms the",
    "reliable root cause",
    "reliability of the diagnosis",
)
_INSUFFICIENT_EVIDENCE_SUMMARY = (
    "Available evidence is insufficient to determine a reliable root cause. "
    "The observed operational condition requires further verification."
)
_PROBABLE_COMPONENT_UNCERTAINTY = (
    "The exact causal mechanism or failed component is not confirmed."
)


def _as_aware_timestamp(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _contains_preincident_timestamp(value, incident_at: datetime) -> bool:
    if isinstance(value, list):
        return any(_contains_preincident_timestamp(item, incident_at) for item in value)
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if key in _TEMPORAL_KEYS:
            timestamp = _as_aware_timestamp(item)
            if timestamp is not None and timestamp < incident_at:
                return True
        if isinstance(item, (dict, list)) and _contains_preincident_timestamp(item, incident_at):
            return True
    return False


def _contains_overconfident_language(*texts: str) -> bool:
    combined = " ".join(text for text in texts if text).casefold()
    cleaned = (
        combined.replace("not confirmed", " ")
        .replace("unconfirmed", " ")
        .replace("not reliable", " ")
    )
    return any(phrase in cleaned for phrase in _OVERCONFIDENT_PHRASES)


def _merge_ids(existing: list[str], extra: list[str], allowed: set[str]) -> list[str]:
    return list(dict.fromkeys(item for item in [*existing, *extra] if item in allowed))


def _error(stage: str, exc: Exception, investigation_id: str) -> dict:
    # Stack locations aid debugging; arbitrary exception bodies never enter durable results.
    logger.error("Investigation %s failed stage=%s type=%s\n%s", investigation_id,
        stage, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))
    return {
        "status": InvestigationStatus.FAILED,
        "error": InvestigationError(
            stage=stage,
            error_type=type(exc).__name__,
            message=f"Investigation failed at {stage}. Consult server logs.",
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
            return _error("resolve_context", exc, state["investigation_id"])

    def gather_initial_evidence(self, state: InvestigationState) -> dict:
        try:
            ctx = self._reconstruct_context(state)
            evidence = self.runtime.tools.gather_initial(ctx, state["trigger"])
        except Exception as exc:
            return _error("gather_initial_evidence", exc, state["investigation_id"])
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
            "approvedTelemetryMetricGroups": [item.value for item in TelemetryMetricGroup],
        }
        try:
            diagnosis = self.runtime.provider.diagnose(payload)
            diagnosis = self._sanitize_diagnosis(diagnosis, state)
        except Exception as exc:
            return {"iteration_count": next_iteration, **_error("analyze", exc, state["investigation_id"])}
        useful_requests, skipped_attempts = self._new_requests(
            diagnosis.requested_information,
            state,
        )
        if diagnosis.can_conclude:
            useful_requests = []
        limit_reached = bool(
            not diagnosis.can_conclude
            and next_iteration >= state["max_iterations"]
            and diagnosis.requested_information
        )
        if limit_reached:
            skipped_attempts.extend(
                self._request_attempt(
                    request,
                    EvidenceRequestOutcome.ITERATION_LIMIT_REACHED,
                )
                for request in useful_requests
            )
        expansion_exhausted = bool(not diagnosis.can_conclude and not useful_requests)
        diagnosis = diagnosis.model_copy(update={"requested_information": useful_requests})
        hypotheses = self._merge_hypotheses(state["hypotheses"], diagnosis.hypotheses)
        contradictions = self._merge_contradictions(
            state["contradictions"], diagnosis.contradictions
        )
        return {
            "diagnosis": diagnosis,
            "hypotheses": hypotheses,
            "requested_information": useful_requests,
            "evidence_request_history": [
                *state["evidence_request_history"],
                *skipped_attempts,
            ],
            "contradictions": contradictions,
            "iteration_count": next_iteration,
            "iteration_limit_reached": limit_reached,
            "evidence_expansion_exhausted": expansion_exhausted,
            "status": InvestigationStatus.ANALYZING,
        }

    def gather_requested_evidence(self, state: InvestigationState) -> dict:
        try:
            ctx = self._reconstruct_context(state)
            additional = self.runtime.tools.gather_requested(ctx, state["requested_information"])
        except Exception as exc:
            return _error("gather_requested_evidence", exc, state["investigation_id"])
        attempts = []
        for request, evidence in zip(state["requested_information"], additional, strict=False):
            outcome = {
                EvidenceStatus.AVAILABLE: EvidenceRequestOutcome.AVAILABLE,
                EvidenceStatus.UNAVAILABLE: EvidenceRequestOutcome.UNAVAILABLE,
                EvidenceStatus.UNSUPPORTED: EvidenceRequestOutcome.UNSUPPORTED,
                EvidenceStatus.ERROR: EvidenceRequestOutcome.ERROR,
            }[evidence.status or EvidenceStatus.UNAVAILABLE]
            attempts.append(self._request_attempt(request, outcome, [evidence.evidence_id]))
        return {
            "evidence": [*state["evidence"], *additional],
            "requested_information": [],
            "evidence_request_history": [*state["evidence_request_history"], *attempts],
            "status": InvestigationStatus.ANALYZING,
        }

    def build_conclusion(self, state: InvestigationState) -> dict:
        payload = {
            "trigger": _json(state["trigger"]),
            "operationalContext": _json(state["operational_context"]),
            "evidence": _json(state["evidence"]),
            "diagnosis": _json(state["diagnosis"]),
            "iterationLimitReached": state["iteration_limit_reached"],
            "evidenceExpansionExhausted": state["evidence_expansion_exhausted"],
        }
        try:
            conclusion = self.runtime.provider.build_conclusion(payload)
            conclusion = self._sanitize_conclusion(conclusion, state)
        except Exception as exc:
            return _error("build_conclusion", exc, state["investigation_id"])
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
            return _error("build_recommendation", exc, state["investigation_id"])
        conclusion = state["conclusion"]
        status = (
            conclusion.diagnosis_status if conclusion is not None else DiagnosisStatus.INCONCLUSIVE
        )
        if conclusion is None or status == DiagnosisStatus.INCONCLUSIVE:
            recommendation = recommendation.model_copy(
                update={
                    "description": (
                        "Verify the observed operational condition and collect the missing "
                        "evidence before any intervention."
                    ),
                    "rationale": (
                        "This investigation did not establish a reliable root cause; human "
                        "validation remains required."
                    ),
                }
            )
        elif status == DiagnosisStatus.PROBABLE and _contains_overconfident_language(
            recommendation.description,
            recommendation.rationale,
        ):
            recommendation = recommendation.model_copy(
                update={
                    "description": (
                        "Verify the probable cause with an operator before any intervention."
                    ),
                    "rationale": (
                        "The evidence supports a probable cause, but it is not confirmed; "
                        "human validation remains required."
                    ),
                }
            )
        return {
            "recommendation": recommendation,
            "status": (
                InvestigationStatus.COMPLETED
                if status == DiagnosisStatus.CONFIRMED
                else InvestigationStatus.COMPLETED_WITH_UNCERTAINTY
            ),
            "completed_at": datetime.now(timezone.utc),
        }

    def persist(self, state: InvestigationState) -> dict:
        completed_at = state["completed_at"] or datetime.now(timezone.utc)
        final_state = {**state, "completed_at": completed_at}
        try:
            self.runtime.persister(self.runtime.session, final_state)
        except Exception as exc:
            _error("persist", exc, state["investigation_id"])
            self.runtime.session.rollback()
            raise InvestigationPersistenceError("Investigation result could not be saved") from exc
        return {"completed_at": completed_at}

    def _reconstruct_context(self, state: InvestigationState) -> OperationalContext:
        serialized = state["operational_context"]
        if serialized is None:
            raise RuntimeError("Operational context was not resolved")
        return self.runtime.context_reconstructor(self.runtime.session, serialized)

    @staticmethod
    def _request_signature(request: EvidenceRequest) -> str:
        canonical = request.model_dump(
            mode="json",
            exclude={"request_id", "reason"},
        )
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()[:24]

    @classmethod
    def _request_attempt(
        cls,
        request: EvidenceRequest,
        outcome: EvidenceRequestOutcome,
        evidence_ids: list[str] | None = None,
    ) -> EvidenceRequestAttempt:
        return EvidenceRequestAttempt(
            signature=cls._request_signature(request),
            request=request,
            outcome=outcome,
            evidence_ids=evidence_ids or [],
            attempted_at=datetime.now(timezone.utc),
        )

    @classmethod
    def _new_requests(
        cls,
        requests: list[EvidenceRequest],
        state: InvestigationState,
    ) -> tuple[list[EvidenceRequest], list[EvidenceRequestAttempt]]:
        attempted = {item.signature for item in state["evidence_request_history"]}
        seen = set(attempted)
        useful = []
        skipped = []
        for request in requests:
            signature = cls._request_signature(request)
            if signature in seen:
                skipped.append(
                    cls._request_attempt(request, EvidenceRequestOutcome.DUPLICATE_SKIPPED)
                )
                continue
            seen.add(signature)
            useful.append(request)
        return useful, skipped

    @staticmethod
    def _merge_hypotheses(
        previous: list[Hypothesis],
        current: list[Hypothesis],
    ) -> list[Hypothesis]:
        merged = {item.hypothesis_id: item for item in previous}
        merged.update({item.hypothesis_id: item for item in current})
        return list(merged.values())

    @staticmethod
    def _merge_contradictions(
        previous: list[Contradiction],
        current: list[Contradiction],
    ) -> list[Contradiction]:
        merged = {
            (item.description, tuple(sorted(item.evidence_ids))): item
            for item in [*previous, *current]
        }
        return list(merged.values())

    @staticmethod
    def _sanitize_diagnosis(
        diagnosis: DiagnosisResult,
        state: InvestigationState,
    ) -> DiagnosisResult:
        evidence_by_id = {
            item.evidence_id: item for item in state["evidence"] if item.available
        }
        hypotheses = []
        for hypothesis in diagnosis.hypotheses:
            supporting = [
                item for item in hypothesis.supporting_evidence_ids if item in evidence_by_id
            ]
            contradictory = [
                item for item in hypothesis.contradictory_evidence_ids if item in evidence_by_id
            ]
            causal_depth = validated_causal_depth(
                hypothesis.statement,
                hypothesis.causal_depth,
                state["trigger"],
            )
            confidence = (
                hypothesis.confidence
                if supporting and causal_depth >= 1
                else ConfidenceLevel.LOW
            )
            hypotheses.append(
                hypothesis.model_copy(
                    update={
                        "supporting_evidence_ids": supporting,
                        "contradictory_evidence_ids": contradictory,
                        "confidence": confidence,
                        "causal_depth": causal_depth,
                    }
                )
            )
        hypotheses.sort(
            key=lambda hypothesis: (
                bool(hypothesis.supporting_evidence_ids),
                hypothesis.causal_depth,
                not bool(hypothesis.contradictory_evidence_ids),
                len(
                    {
                        evidence_by_id[evidence_id].source_tool
                        for evidence_id in hypothesis.supporting_evidence_ids
                    }
                ),
                len(hypothesis.supporting_evidence_ids),
                _CONFIDENCE_RANK[hypothesis.confidence],
            ),
            reverse=True,
        )
        contradictions: list[Contradiction] = []
        for contradiction in diagnosis.contradictions:
            ids = list(
                dict.fromkeys(i for i in contradiction.evidence_ids if i in evidence_by_id)
            )
            if ids:
                contradictions.append(contradiction.model_copy(update={"evidence_ids": ids}))
        return diagnosis.model_copy(
            update={"hypotheses": hypotheses, "contradictions": contradictions}
        )

    @staticmethod
    def _sanitize_conclusion(
        conclusion: InvestigationConclusion,
        state: InvestigationState,
    ) -> InvestigationConclusion:
        evidence_by_id = {
            item.evidence_id: item for item in state["evidence"] if item.available
        }
        fact_ids = {
            item.evidence_id for item in evidence_by_id.values() if item.kind == EvidenceKind.FACT
        }
        metric_ids = {
            item.evidence_id
            for item in evidence_by_id.values()
            if item.kind in {EvidenceKind.DERIVED_METRIC, EvidenceKind.MODEL_PREDICTION}
        }
        backed_hypotheses = [
            item
            for item in state["hypotheses"]
            if item.supporting_evidence_ids and item.causal_depth >= 1
        ]
        backed_hypotheses.sort(
            key=lambda hypothesis: (
                not bool(hypothesis.contradictory_evidence_ids),
                hypothesis.causal_depth,
                len(
                    {
                        evidence_by_id[evidence_id].source_tool
                        for evidence_id in hypothesis.supporting_evidence_ids
                        if evidence_id in evidence_by_id
                    }
                ),
                len(hypothesis.supporting_evidence_ids),
                _CONFIDENCE_RANK[hypothesis.confidence],
            ),
            reverse=True,
        )
        evidence_backed_hypotheses = {
            item.hypothesis_id: item for item in backed_hypotheses
        }
        hypothesis_ids = {item.hypothesis_id for item in state["hypotheses"]}
        updates = {
            "observed_condition": trigger_observation(state["trigger"]),
            "observed_fact_evidence_ids": [
                item for item in conclusion.observed_fact_evidence_ids if item in fact_ids
            ],
            "derived_metric_evidence_ids": [
                item for item in conclusion.derived_metric_evidence_ids if item in metric_ids
            ],
            "supported_hypothesis_ids": [
                item
                for item in conclusion.supported_hypothesis_ids
                if item in hypothesis_ids and item in evidence_backed_hypotheses
            ],
            "contributing_factors": [],
        }
        sanitized_factors: list[ContributingFactor] = []
        for factor in conclusion.contributing_factors:
            ids = list(dict.fromkeys(item for item in factor.evidence_ids if item in evidence_by_id))
            if ids:
                sanitized_factors.append(factor.model_copy(update={"evidence_ids": ids}))
        updates["contributing_factors"] = sanitized_factors
        top = backed_hypotheses[0] if backed_hypotheses else None
        global_contradiction_ids = {
            evidence_id
            for contradiction in state["contradictions"]
            for evidence_id in contradiction.evidence_ids
        }
        top_conflicted = bool(
            top
            and (
                top.contradictory_evidence_ids
                or set(top.supporting_evidence_ids) & global_contradiction_ids
            )
        )
        top_rank = None
        second_rank = None
        if top is not None:
            top_rank = (
                top.causal_depth,
                len({evidence_by_id[item].source_tool for item in top.supporting_evidence_ids}),
                len(top.supporting_evidence_ids),
                _CONFIDENCE_RANK[top.confidence],
            )
        if len(backed_hypotheses) > 1:
            second = backed_hypotheses[1]
            second_rank = (
                second.causal_depth,
                len({evidence_by_id[item].source_tool for item in second.supporting_evidence_ids}),
                len(second.supporting_evidence_ids),
                _CONFIDENCE_RANK[second.confidence],
            )
        clearly_dominant = bool(top_rank is not None and (second_rank is None or top_rank > second_rank))
        incident_at = state["trigger"].occurred_at.astimezone(timezone.utc)

        def _temporal_support(evidence_id: str) -> bool:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                return False
            return bool(
                evidence.metadata.get("causalConfirmation") is True
                or evidence.metadata.get("preIncidentSampleCount", 0) > 0
                or (
                    evidence.observed_at is not None
                    and _as_aware_timestamp(evidence.observed_at) < incident_at
                )
                or _contains_preincident_timestamp(evidence.value, incident_at)
                or _contains_preincident_timestamp(evidence.metadata, incident_at)
            )

        temporal_support = bool(
            top and any(_temporal_support(item) for item in top.supporting_evidence_ids)
        )
        diagnosis = state.get("diagnosis")
        probable_eligible = bool(
            top is not None
            and diagnosis is not None
            and diagnosis.can_conclude
            and top.causal_depth >= 1
            and top.confidence != ConfidenceLevel.LOW
            and not top_conflicted
            and clearly_dominant
            and temporal_support
        )
        authoritative_confirmation = bool(
            top
            and any(
                evidence_by_id[evidence_id].kind == EvidenceKind.FACT
                and evidence_by_id[evidence_id].metadata.get("causalConfirmation") is True
                for evidence_id in top.supporting_evidence_ids
                if evidence_id in evidence_by_id
            )
        )
        confirmed_eligible = bool(
            probable_eligible
            and authoritative_confirmation
            and top is not None
            and top.confidence == ConfidenceLevel.HIGH
            and conclusion.confidence == ConfidenceLevel.HIGH
        )
        confirmed = bool(
            confirmed_eligible
            and conclusion.diagnosis_status == DiagnosisStatus.CONFIRMED
            and conclusion.reliable_root_cause
        )
        uncertainties = list(conclusion.unresolved_uncertainties)
        uncertainties.extend(req.reason for req in state["requested_information"])
        if state["iteration_limit_reached"]:
            gathering_reason = "The maximum evidence-gathering iteration count was reached."
        elif state["evidence_expansion_exhausted"]:
            gathering_reason = "No new supported evidence request remained available."
        else:
            gathering_reason = None
        if confirmed or probable_eligible:
            root_cause = (
                conclusion.root_cause
                if confirmed and conclusion.root_cause
                else top.statement
            )
            updates["observed_fact_evidence_ids"] = _merge_ids(
                updates["observed_fact_evidence_ids"],
                [item for item in top.supporting_evidence_ids if item in fact_ids],
                fact_ids,
            )
            updates["derived_metric_evidence_ids"] = _merge_ids(
                updates["derived_metric_evidence_ids"],
                [item for item in top.supporting_evidence_ids if item in metric_ids],
                metric_ids,
            )
            updates["supported_hypothesis_ids"] = _merge_ids(
                updates["supported_hypothesis_ids"],
                [top.hypothesis_id],
                set(evidence_backed_hypotheses),
            )
            updates["causal_depth"] = top.causal_depth
            updates["contributing_factors"] = [
                factor
                for factor in sanitized_factors
                if factor.statement.casefold() != root_cause.casefold()
            ]
            if gathering_reason:
                uncertainties.append(gathering_reason)
            if confirmed:
                updates.update(
                    {
                        "diagnosis_status": DiagnosisStatus.CONFIRMED,
                        "summary": (
                            "Authoritative evidence supports the following root cause: "
                            f"{root_cause}"
                        ),
                        "root_cause": root_cause,
                        "reliable_root_cause": True,
                        "confidence": ConfidenceLevel.HIGH,
                        "unresolved_uncertainties": list(dict.fromkeys(uncertainties)),
                    }
                )
            else:
                uncertainties.append(_PROBABLE_COMPONENT_UNCERTAINTY)
                conclusion_confidence = (
                    top.confidence
                    if conclusion.confidence == ConfidenceLevel.LOW
                    else min(
                        (top.confidence, conclusion.confidence),
                        key=lambda item: _CONFIDENCE_RANK[item],
                    )
                )
                updates.update(
                    {
                        "diagnosis_status": DiagnosisStatus.PROBABLE,
                        "summary": (
                            "The available evidence supports the following as the best current "
                            f"explanation: {root_cause}"
                        ),
                        "root_cause": root_cause,
                        "reliable_root_cause": False,
                        "confidence": conclusion_confidence,
                        "unresolved_uncertainties": list(dict.fromkeys(uncertainties)),
                    }
                )
        else:
            depth_zero_supported = any(
                item.supporting_evidence_ids and item.causal_depth == 0
                for item in state["hypotheses"]
            )
            if depth_zero_supported:
                reason = "The proposed explanation restates the observed symptom without a deeper causal mechanism."
            elif diagnosis is not None and not diagnosis.can_conclude:
                reason = "The diagnosis explicitly states that available evidence cannot support a conclusion."
            elif top_conflicted or (len(backed_hypotheses) > 1 and not clearly_dominant):
                reason = "Evidence cannot discriminate between competing hypotheses."
            elif top is None or top.confidence == ConfidenceLevel.LOW:
                reason = "No evidence-backed hypothesis supports a probable cause."
            elif gathering_reason:
                reason = gathering_reason
            else:
                reason = "Available evidence cannot support a probable or confirmed cause."
            uncertainties.append(reason)
            if gathering_reason and gathering_reason != reason:
                uncertainties.append(gathering_reason)
            updates.update(
                {
                    "diagnosis_status": DiagnosisStatus.INCONCLUSIVE,
                    "summary": _INSUFFICIENT_EVIDENCE_SUMMARY,
                    "root_cause": None,
                    "reliable_root_cause": False,
                    "causal_depth": 0,
                    "contributing_factors": [],
                    "confidence": ConfidenceLevel.LOW,
                    "unresolved_uncertainties": list(dict.fromkeys(uncertainties)),
                }
            )
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
