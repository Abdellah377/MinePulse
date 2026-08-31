"""Investigation node implementations with injected operational and LLM boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from time import monotonic
import traceback
from uuid import UUID

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
from app.ai.debug import (
    DebugEventType,
    InvestigationDebugSink,
    NullDebugRecorder,
    ValidationCheck,
    compact_conclusion,
    compact_diagnosis,
    compact_evidence,
    compact_preview,
    consume_provider_metrics,
)
from app.ai.llm.provider import LLMProvider
from app.ai.persistence import InvestigationPersistenceError, persist_investigation
from app.ai.routers import route_after_analysis
from app.ai.state import InvestigationState
from app.ai.tools import EvidenceToolRegistry
from app.db.models import AiInvestigation
from app.services.operational.context import OperationalContext


@dataclass
class InvestigationRuntime:
    session: Session
    provider: LLMProvider
    tools: EvidenceToolRegistry
    context_resolver: Callable[[Session, InvestigationTrigger], OperationalContext]
    context_reconstructor: Callable[[Session, ResolvedOperationalContext], OperationalContext]
    persister: Callable[[Session, InvestigationState], object] = persist_investigation
    debug: InvestigationDebugSink = field(default_factory=NullDebugRecorder)


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


def _error(stage: str, exc: Exception, investigation_id: str, debug: InvestigationDebugSink | None = None) -> dict:
    # Stack locations aid debugging; arbitrary exception bodies never enter durable results.
    logger.error("Investigation %s failed stage=%s type=%s\n%s", investigation_id,
        stage, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))
    if debug is not None:
        event = (
            DebugEventType.PROVIDER_FAILURE
            if stage in {"analyze", "build_conclusion", "build_recommendation"}
            else DebugEventType.INVESTIGATION_FAILED
        )
        debug.record(
            event,
            stage=stage,
            summary=f"Investigation failed at {stage} ({type(exc).__name__})",
            metadata={
                "error_type": type(exc).__name__,
                "request_id": getattr(exc, "request_id", None),
            },
        )
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

    def _fail(self, stage: str, exc: Exception, investigation_id: str) -> dict:
        return _error(stage, exc, investigation_id, self.runtime.debug)

    def _llm(self, stage: str, call, compact_meta) -> object:
        started = monotonic()
        try:
            result = call()
        except Exception:
            self.runtime.debug.add_llm_metrics(consume_provider_metrics(self.runtime.provider))
            raise
        metrics = consume_provider_metrics(self.runtime.provider)
        duration = int(metrics["duration_ms"]) if metrics and isinstance(metrics.get("duration_ms"), int) else int(
            (monotonic() - started) * 1000
        )
        self.runtime.debug.add_llm_metrics(metrics or {"duration_ms": duration, "model": self.runtime.provider.model_name})
        metadata = compact_meta(result) if callable(compact_meta) else compact_meta
        self.runtime.debug.record(
            DebugEventType.LLM_CALL,
            stage=stage,
            summary=f"Structured LLM call ({stage})",
            duration_ms=duration,
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        return result

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
            self.runtime.debug.record(
                DebugEventType.CONTEXT_RESOLVED,
                stage="resolve_context",
                summary=f"Resolved {resolved.site_code} / shift {resolved.shift_id}",
                metadata={
                    "site_id": resolved.site_id,
                    "site_code": resolved.site_code,
                    "shift_id": resolved.shift_id,
                    "window_start": resolved.window_start.isoformat() if resolved.window_start else None,
                    "window_end": resolved.window_end.isoformat() if resolved.window_end else None,
                },
            )
            return {
                "operational_context": resolved,
                "status": InvestigationStatus.GATHERING_EVIDENCE,
            }
        except Exception as exc:
            return self._fail("resolve_context", exc, state["investigation_id"])

    def gather_initial_evidence(self, state: InvestigationState) -> dict:
        try:
            ctx = self._reconstruct_context(state)
            evidence = self.runtime.tools.gather_initial(ctx, state["trigger"])
        except Exception as exc:
            return self._fail("gather_initial_evidence", exc, state["investigation_id"])
        self.runtime.debug.mark_initial_count(len(evidence))
        self.runtime.debug.record(
            DebugEventType.INITIAL_EVIDENCE_GATHERED,
            stage="gather_initial_evidence",
            summary=f"Gathered {len(evidence)} initial evidence item(s)",
            metadata={
                "count": len(evidence),
                "ids": [item.evidence_id for item in evidence],
                "kinds": [getattr(item.kind, "value", item.kind) for item in evidence],
                "tools": [item.source_tool for item in evidence],
                "items": [compact_evidence(item) for item in evidence],
            },
        )
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
            diagnosis = self._llm("analyze", lambda: self.runtime.provider.diagnose(payload), compact_diagnosis)
            diagnosis = self._sanitize_diagnosis(diagnosis, state, self.runtime.debug)
        except Exception as exc:
            return {"iteration_count": next_iteration, **self._fail("analyze", exc, state["investigation_id"])}
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
        if useful_requests:
            self.runtime.debug.record(
                DebugEventType.ADDITIONAL_EVIDENCE_REQUESTED,
                stage="analyze",
                summary=f"Requested {len(useful_requests)} additional evidence type(s)",
                metadata={
                    "types": [request.request_type.value for request in useful_requests],
                    "reasons": [compact_preview(request.reason) for request in useful_requests],
                },
            )
        preview = {
            **state,
            "diagnosis": diagnosis,
            "requested_information": useful_requests,
            "iteration_count": next_iteration,
            "iteration_limit_reached": limit_reached,
            "evidence_expansion_exhausted": expansion_exhausted,
            "status": InvestigationStatus.ANALYZING,
        }
        next_node = route_after_analysis(preview)
        self.runtime.debug.record(
            DebugEventType.ROUTER_DECISION,
            stage="analyze",
            summary=f"Route to {next_node}",
            metadata={
                "can_conclude": diagnosis.can_conclude,
                "request_count": len(useful_requests),
                "iteration_count": next_iteration,
                "max_iterations": state["max_iterations"],
                "evidence_expansion_exhausted": expansion_exhausted,
                "next_node": next_node,
            },
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
            return self._fail("gather_requested_evidence", exc, state["investigation_id"])
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
            conclusion = self._llm(
                "build_conclusion",
                lambda: self.runtime.provider.build_conclusion(payload),
                lambda item: compact_conclusion(item).model_dump() if compact_conclusion(item) else {},
            )
            self.runtime.debug.set_proposed_conclusion(conclusion)
            conclusion = self._sanitize_conclusion(conclusion, state, self.runtime.debug)
            snapshot = compact_conclusion(conclusion)
            self.runtime.debug.record(
                DebugEventType.CONCLUSION_BUILT,
                stage="build_conclusion",
                summary=f"Backend conclusion {getattr(conclusion.diagnosis_status, 'value', conclusion.diagnosis_status)}",
                metadata=snapshot.model_dump() if snapshot else {},
            )
        except Exception as extra:
            return self._fail("build_conclusion", extra, state["investigation_id"])
        return {
            "conclusion": conclusion,
            "status": InvestigationStatus.BUILDING_RECOMMENDATION,
        }

    def build_recommendation(self, state: InvestigationState) -> dict:
        evidence = list(state["evidence"])
        payload = {
            "trigger": _json(state["trigger"]),
            "conclusion": _json(state["conclusion"]),
            "evidence": _json(evidence),
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
            proposed = self._llm(
                "build_recommendation",
                lambda: self.runtime.provider.build_recommendation(payload),
                lambda item: {
                    "action_type": getattr(item.action_type, "value", item.action_type),
                    "description": compact_preview(item.description),
                    "evidence_ids": list(item.evidence_ids),
                },
            )
            recommendation = proposed
            valid_evidence = {
                item.evidence_id for item in evidence if item.available
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
            return self._fail("build_recommendation", exc, state["investigation_id"])
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
        rewritten = (
            proposed.description != recommendation.description
            or proposed.rationale != recommendation.rationale
            or list(proposed.evidence_ids) != list(recommendation.evidence_ids)
            or proposed.target_equipment_id != recommendation.target_equipment_id
            or proposed.target_zone_id != recommendation.target_zone_id
            or proposed.human_validation_required != recommendation.human_validation_required
        )
        if rewritten:
            self.runtime.debug.record(
                DebugEventType.VALIDATION_CHECK,
                stage="build_recommendation",
                summary="Recommendation text or citations were rewritten",
                metadata={"check_id": "RECOMMENDATION_SANITIZED", "passed": False},
            )
        self.runtime.debug.record(
            DebugEventType.RECOMMENDATION_BUILT,
            stage="build_recommendation",
            summary=getattr(recommendation.action_type, "value", str(recommendation.action_type)),
            metadata={
                "proposed_description": compact_preview(proposed.description),
                "final_description": compact_preview(recommendation.description),
                "evidence_ids": list(recommendation.evidence_ids),
                "sanitized": rewritten,
            },
        )
        return {
            "recommendation": recommendation,
            "evidence": evidence,
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
            row = self.runtime.persister(self.runtime.session, final_state)
        except Exception as exc:
            _error("persist", exc, state["investigation_id"], self.runtime.debug)
            self.runtime.session.rollback()
            raise InvestigationPersistenceError("Investigation result could not be saved") from exc
        self._store_debug_trace(row, final_state)
        return {"completed_at": completed_at}

    def _store_debug_trace(self, row, state: InvestigationState) -> None:
        try:
            dump = self.runtime.debug.finish(state)
            if dump is None:
                return
            target = row if row is not None and not isinstance(row, dict) else None
            if target is None:
                getter = getattr(self.runtime.session, "get", None)
                if callable(getter):
                    try:
                        target = getter(AiInvestigation, UUID(state["investigation_id"]))
                    except Exception:
                        target = None
            if target is None:
                return
            target.debug_trace = dump
            commit = getattr(self.runtime.session, "commit", None)
            if callable(commit):
                commit()
        except Exception:
            logger.exception("Investigation debug trace persist failed")

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
        debug: InvestigationDebugSink | None = None,
    ) -> DiagnosisResult:
        sink = debug or NullDebugRecorder()
        originals = {item.hypothesis_id: item for item in diagnosis.hypotheses}
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
        top_id = hypotheses[0].hypothesis_id if hypotheses else None
        for hypothesis in hypotheses:
            original = originals.get(hypothesis.hypothesis_id)
            reasons = []
            if hypothesis.causal_depth < 1:
                reasons.append("CAUSAL_DEPTH_TOO_LOW")
            if not hypothesis.supporting_evidence_ids:
                reasons.append("NO_VALID_SUPPORTING_EVIDENCE")
            fabricated = []
            if original is not None:
                fabricated = [
                    item
                    for item in [*original.supporting_evidence_ids, *original.contradictory_evidence_ids]
                    if item not in evidence_by_id
                ]
            if fabricated:
                reasons.append("FABRICATED_EVIDENCE_ID")
            sink.record(
                DebugEventType.HYPOTHESIS_EVALUATED,
                stage="analyze",
                summary=hypothesis.statement[:200],
                metadata={
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "statement": hypothesis.statement,
                    "confidence": getattr(hypothesis.confidence, "value", hypothesis.confidence),
                    "causal_depth": hypothesis.causal_depth,
                    "supporting_evidence_ids": list(hypothesis.supporting_evidence_ids),
                    "contradictory_evidence_ids": list(hypothesis.contradictory_evidence_ids),
                    "survived": bool(hypothesis.supporting_evidence_ids and hypothesis.causal_depth >= 1),
                    "is_top": hypothesis.hypothesis_id == top_id,
                    "reason_codes": reasons,
                },
            )
        return diagnosis.model_copy(
            update={"hypotheses": hypotheses, "contradictions": contradictions}
        )

    @staticmethod
    def _sanitize_conclusion(
        conclusion: InvestigationConclusion,
        state: InvestigationState,
        debug: InvestigationDebugSink | None = None,
    ) -> InvestigationConclusion:
        sink = debug or NullDebugRecorder()
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
        depth_zero_supported = any(
            item.supporting_evidence_ids and item.causal_depth == 0
            for item in state["hypotheses"]
        )
        original_ids = set(conclusion.observed_fact_evidence_ids) | set(
            conclusion.derived_metric_evidence_ids
        )
        for hyp in state["hypotheses"]:
            original_ids.update(hyp.supporting_evidence_ids)
            original_ids.update(hyp.contradictory_evidence_ids)
        fabricated = sorted(item for item in original_ids if item not in evidence_by_id)
        checks = [
            ValidationCheck(
                check_id="FABRICATED_EVIDENCE_ID",
                passed=not fabricated,
                detail=(("Dropped IDs: " + ", ".join(fabricated))[:400] if fabricated else "No fabricated evidence IDs"),
            ),
            ValidationCheck(
                check_id="CAUSAL_DEPTH_TOO_LOW",
                passed=not any(
                    item.supporting_evidence_ids and item.causal_depth < 1
                    for item in state["hypotheses"]
                ),
                detail="A supported hypothesis has causal_depth < 1"
                if any(item.supporting_evidence_ids and item.causal_depth < 1 for item in state["hypotheses"])
                else "Causal depth gate did not exclude supported hypotheses",
            ),
            ValidationCheck(
                check_id="SYMPTOM_RESTATEMENT",
                passed=not depth_zero_supported,
                detail="At least one hypothesis restates the observed symptom"
                if depth_zero_supported
                else "No symptom-restatement hypothesis",
            ),
            ValidationCheck(
                check_id="DIAGNOSIS_CANNOT_CONCLUDE",
                passed=diagnosis is None or diagnosis.can_conclude,
                detail="diagnosis.can_conclude is required for probable_eligible",
            ),
            ValidationCheck(
                check_id="STRONG_CONTRADICTION",
                passed=not top_conflicted,
                detail="Top hypothesis is conflicted" if top_conflicted else "No strong contradiction on top hypothesis",
            ),
            ValidationCheck(
                check_id="NO_CLEARLY_DOMINANT_HYPOTHESIS",
                passed=clearly_dominant,
                detail="No clearly dominant backed hypothesis" if not clearly_dominant else "Top hypothesis is dominant",
            ),
            ValidationCheck(
                check_id="TEMPORAL_SUPPORT_MISSING",
                passed=bool(temporal_support),
                detail="Top hypothesis lacks pre-incident temporal support"
                if not temporal_support
                else "Temporal support present",
            ),
            ValidationCheck(
                check_id="NO_VALID_SUPPORTING_EVIDENCE",
                passed=top is not None,
                detail="No evidence-backed hypothesis with causal_depth >= 1"
                if top is None
                else "Backed hypothesis present",
            ),
            ValidationCheck(
                check_id="CONFIRMED_WITHOUT_AUTHORITATIVE_EVIDENCE",
                passed=not (
                    conclusion.diagnosis_status == DiagnosisStatus.CONFIRMED
                    and not authoritative_confirmation
                ),
                detail="LLM proposed CONFIRMED without causalConfirmation evidence"
                if conclusion.diagnosis_status == DiagnosisStatus.CONFIRMED and not authoritative_confirmation
                else "Confirmed status is consistent with authoritative evidence",
            ),
        ]
        sanitized = conclusion.model_copy(update=updates)
        try:
            for check in checks:
                sink.record(
                    DebugEventType.VALIDATION_CHECK,
                    stage="build_conclusion",
                    summary=f"{check.check_id} {'passed' if check.passed else 'failed'}",
                    metadata={"check_id": check.check_id, "passed": check.passed, "detail": check.detail},
                )
            sink.set_validation(checks)
            if (
                conclusion.diagnosis_status != sanitized.diagnosis_status
                or conclusion.reliable_root_cause != sanitized.reliable_root_cause
            ):
                sink.record(
                    DebugEventType.STATUS_DOWNGRADED,
                    stage="build_conclusion",
                    summary=(
                        f"{getattr(conclusion.diagnosis_status, 'value', conclusion.diagnosis_status)}"
                        f" -> {getattr(sanitized.diagnosis_status, 'value', sanitized.diagnosis_status)}"
                    ),
                    metadata={
                        "llm_diagnosis_status": getattr(conclusion.diagnosis_status, "value", conclusion.diagnosis_status),
                        "final_diagnosis_status": getattr(sanitized.diagnosis_status, "value", sanitized.diagnosis_status),
                        "llm_reliable_root_cause": conclusion.reliable_root_cause,
                        "final_reliable_root_cause": sanitized.reliable_root_cause,
                    },
                )
        except Exception:
            logger.exception("Investigation debug validation record failed")
        return sanitized

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
