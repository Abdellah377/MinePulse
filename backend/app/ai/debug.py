"""Developer-only investigation observability. Never imported by operator contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from typing import Any, Protocol
from uuid import uuid4
import json
import logging
import re

from pydantic import BaseModel, ConfigDict, Field

from app.ai.contracts import (
    DiagnosisResult,
    EvidenceItem,
    EvidenceStatus,
    InvestigationConclusion,
    InvestigationStatus,
)
from app.ai.state import InvestigationState

logger = logging.getLogger(__name__)

MAX_EVENTS = 120
PREVIEW_LIMIT = 400
_SECRET_KEY = re.compile(r"api[_-]?key|authorization|password|secret|token", re.I)
_PROVIDER_STAGES = {"analyze", "build_conclusion", "build_recommendation"}
_EVIDENCE_STAGES = {"gather_initial_evidence", "gather_requested_evidence"}
_FORBIDDEN_FIELDS = {
    "reasoning",
    "chain_of_thought",
    "chainOfThought",
    "private_reasoning",
    "system_prompt",
    "prompt",
}


class DebugEventType(str, Enum):
    INVESTIGATION_STARTED = "INVESTIGATION_STARTED"
    CONTEXT_RESOLVED = "CONTEXT_RESOLVED"
    INITIAL_EVIDENCE_GATHERED = "INITIAL_EVIDENCE_GATHERED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    LLM_CALL = "LLM_CALL"
    ADDITIONAL_EVIDENCE_REQUESTED = "ADDITIONAL_EVIDENCE_REQUESTED"
    ROUTER_DECISION = "ROUTER_DECISION"
    HYPOTHESIS_EVALUATED = "HYPOTHESIS_EVALUATED"
    VALIDATION_CHECK = "VALIDATION_CHECK"
    STATUS_DOWNGRADED = "STATUS_DOWNGRADED"
    CONCLUSION_BUILT = "CONCLUSION_BUILT"
    RECOMMENDATION_BUILT = "RECOMMENDATION_BUILT"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVESTIGATION_COMPLETED = "INVESTIGATION_COMPLETED"
    INVESTIGATION_FAILED = "INVESTIGATION_FAILED"


class InvestigationStopReason(str, Enum):
    CONFIRMED_CAUSE = "CONFIRMED_CAUSE"
    PROBABLE_CAUSE = "PROBABLE_CAUSE"
    EVIDENCE_EXHAUSTED = "EVIDENCE_EXHAUSTED"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    NO_DOMINANT_HYPOTHESIS = "NO_DOMINANT_HYPOTHESIS"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    TOOL_FAILURE = "TOOL_FAILURE"
    INCONCLUSIVE_AFTER_VALIDATION = "INCONCLUSIVE_AFTER_VALIDATION"


class DebugModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class DebugEvent(DebugModel):
    event_id: str
    sequence: int
    timestamp: datetime
    stage: str
    event_type: DebugEventType
    summary: str = Field(max_length=400)
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationCheck(DebugModel):
    check_id: str
    passed: bool
    detail: str = Field(max_length=400)


class EvidenceCoverage(DebugModel):
    initial_count: int = 0
    additional_requested: int = 0
    available: int = 0
    unavailable: int = 0
    contradictory: int = 0
    iterations: int = 0
    max_iterations: int = 0
    families: list[str] = Field(default_factory=list)


class DebugUsage(DebugModel):
    model: str | None = None
    request_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class DebugDurations(DebugModel):
    total: int | None = None
    llm: int = 0
    evidence: int = 0


class CompactConclusion(DebugModel):
    diagnosis_status: str | None = None
    root_cause: str | None = None
    reliable_root_cause: bool | None = None
    confidence: str | None = None
    supported_hypothesis_ids: list[str] = Field(default_factory=list)


class InvestigationDebugTrace(DebugModel):
    investigation_id: str
    graph_version: str | None = None
    provider: str | None = None
    model: str | None = None
    stop_reason: InvestigationStopReason | None = None
    events: list[DebugEvent] = Field(default_factory=list)
    llm_proposed: CompactConclusion | None = None
    backend_enforced: CompactConclusion | None = None
    validation_checks: list[ValidationCheck] = Field(default_factory=list)
    coverage: EvidenceCoverage = Field(default_factory=EvidenceCoverage)
    usage: DebugUsage = Field(default_factory=DebugUsage)
    wall_durations_ms: DebugDurations = Field(default_factory=DebugDurations)
    trigger: dict[str, Any] = Field(default_factory=dict)
    recommendation: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class InvestigationDebugSink(Protocol):
    enabled: bool

    def record(
        self,
        event_type: DebugEventType | str,
        *,
        stage: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None: ...

    def add_llm_metrics(self, metrics: dict[str, Any] | None) -> None: ...

    def add_evidence_duration(self, duration_ms: int) -> None: ...

    def mark_initial_count(self, count: int) -> None: ...

    def set_proposed_conclusion(self, conclusion: InvestigationConclusion) -> None: ...

    def set_validation(self, checks: list[ValidationCheck]) -> None: ...

    def finish(self, state: InvestigationState) -> dict[str, Any] | None: ...


class NullDebugRecorder:
    """No-op sink used when AI_DEBUG_MODE is false."""

    enabled = False

    def record(self, event_type, *, stage, summary, metadata=None, duration_ms=None) -> None:
        return None

    def add_llm_metrics(self, metrics: dict[str, Any] | None) -> None:
        return None

    def add_evidence_duration(self, duration_ms: int) -> None:
        return None

    def mark_initial_count(self, count: int) -> None:
        return None

    def set_proposed_conclusion(self, conclusion: InvestigationConclusion) -> None:
        return None

    def set_validation(self, checks: list[ValidationCheck]) -> None:
        return None

    def finish(self, state: InvestigationState) -> dict[str, Any] | None:
        return None


def compact_preview(value: Any, limit: int = PREVIEW_LIMIT) -> str | None:
    if value is None:
        return None
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    except TypeError:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN_FIELDS or _SECRET_KEY.search(key):
                continue
            cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value[:40]]
    return value


def compact_conclusion(conclusion: InvestigationConclusion | None) -> CompactConclusion | None:
    if conclusion is None:
        return None
    return CompactConclusion(
        diagnosis_status=getattr(conclusion.diagnosis_status, "value", conclusion.diagnosis_status),
        root_cause=conclusion.root_cause,
        reliable_root_cause=conclusion.reliable_root_cause,
        confidence=getattr(conclusion.confidence, "value", conclusion.confidence),
        supported_hypothesis_ids=list(conclusion.supported_hypothesis_ids),
    )


def compact_diagnosis(diagnosis: DiagnosisResult | None) -> dict[str, Any]:
    if diagnosis is None:
        return {}
    return {
        "can_conclude": diagnosis.can_conclude,
        "confidence": getattr(diagnosis.confidence, "value", diagnosis.confidence),
        "hypothesis_count": len(diagnosis.hypotheses),
        "hypotheses": [
            {
                "hypothesis_id": item.hypothesis_id,
                "statement": item.statement,
                "confidence": getattr(item.confidence, "value", item.confidence),
                "causal_depth": item.causal_depth,
                "supporting_evidence_ids": list(item.supporting_evidence_ids),
                "contradictory_evidence_ids": list(item.contradictory_evidence_ids),
            }
            for item in diagnosis.hypotheses
        ],
        "requested_types": [item.request_type.value for item in diagnosis.requested_information],
    }


def compact_evidence(item: EvidenceItem) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "kind": getattr(item.kind, "value", item.kind),
        "source_tool": item.source_tool,
        "source_service": item.source_service,
        "metric": item.metric,
        "available": item.available,
        "status": getattr(item.status, "value", item.status),
        "observed_at": item.observed_at.isoformat() if item.observed_at else None,
        "preview": compact_preview(item.value) if item.available else None,
    }


def stop_reason_for(state: InvestigationState, *, no_dominant: bool = False) -> InvestigationStopReason:
    error = state.get("error")
    if error is not None:
        if error.stage in _PROVIDER_STAGES or error.error_type.startswith("Provider"):
            return InvestigationStopReason.PROVIDER_FAILURE
        if error.stage in _EVIDENCE_STAGES:
            return InvestigationStopReason.TOOL_FAILURE
        return InvestigationStopReason.PROVIDER_FAILURE
    conclusion = state.get("conclusion")
    status = getattr(getattr(conclusion, "diagnosis_status", None), "value", None)
    if status is None and conclusion is not None:
        status = str(conclusion.diagnosis_status)
    if status == "CONFIRMED":
        return InvestigationStopReason.CONFIRMED_CAUSE
    if status == "PROBABLE":
        return InvestigationStopReason.PROBABLE_CAUSE
    if state.get("iteration_limit_reached"):
        return InvestigationStopReason.MAX_ITERATIONS
    if state.get("evidence_expansion_exhausted"):
        return InvestigationStopReason.EVIDENCE_EXHAUSTED
    if no_dominant:
        return InvestigationStopReason.NO_DOMINANT_HYPOTHESIS
    return InvestigationStopReason.INCONCLUSIVE_AFTER_VALIDATION


class InvestigationDebugRecorder:
    enabled = True

    def __init__(self, investigation_id: str, *, model: str | None = None):
        self.investigation_id = investigation_id
        self._started = monotonic()
        self._events: list[DebugEvent] = []
        self._llm_ms = 0
        self._evidence_ms = 0
        self._usage = DebugUsage(model=model)
        self._proposed: CompactConclusion | None = None
        self._checks: list[ValidationCheck] = []
        self._initial_count = 0
        self._no_dominant = False
        self._model = model
        self.last_dump: dict[str, Any] | None = None

    def record(
        self,
        event_type: DebugEventType | str,
        *,
        stage: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        try:
            if len(self._events) >= MAX_EVENTS:
                return
            kind = (
                event_type
                if isinstance(event_type, DebugEventType)
                else DebugEventType(event_type)
            )
            self._events.append(
                DebugEvent(
                    event_id=f"dbg-{uuid4()}",
                    sequence=len(self._events) + 1,
                    timestamp=datetime.now(timezone.utc),
                    stage=stage,
                    event_type=kind,
                    summary=summary[:400],
                    duration_ms=duration_ms,
                    metadata=redact(metadata or {}),
                )
            )
        except Exception:
            logger.exception("Investigation debug event failed")

    def add_llm_metrics(self, metrics: dict[str, Any] | None) -> None:
        if not metrics:
            return
        try:
            duration = metrics.get("duration_ms")
            if isinstance(duration, (int, float)):
                self._llm_ms += int(duration)
            self._usage.request_count += 1
            if self._usage.model is None:
                self._usage.model = metrics.get("model")
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                value = metrics.get(field)
                if isinstance(value, int):
                    current = getattr(self._usage, field) or 0
                    setattr(self._usage, field, current + value)
        except Exception:
            logger.exception("Investigation debug usage accounting failed")

    def add_evidence_duration(self, duration_ms: int) -> None:
        self._evidence_ms += max(0, duration_ms)

    def set_proposed_conclusion(self, conclusion: InvestigationConclusion) -> None:
        self._proposed = compact_conclusion(conclusion)

    def set_validation(self, checks: list[ValidationCheck]) -> None:
        self._checks = list(checks)
        self._no_dominant = any(
            item.check_id == "NO_CLEARLY_DOMINANT_HYPOTHESIS" and not item.passed
            for item in checks
        )

    def mark_initial_count(self, count: int) -> None:
        self._initial_count = count

    def finish(self, state: InvestigationState) -> dict[str, Any] | None:
        try:
            conclusion = state.get("conclusion")
            evidence = state.get("evidence") or []
            history = state.get("evidence_request_history") or []
            families = sorted({item.source_tool for item in evidence if item.source_tool})
            requested_unavailable = [
                item.source_tool
                for item in evidence
                if not item.available and item.status in {
                    EvidenceStatus.UNAVAILABLE,
                    EvidenceStatus.UNSUPPORTED,
                    EvidenceStatus.ERROR,
                }
            ]
            coverage_families = []
            for name in families:
                mark = "✗" if name in requested_unavailable and not any(
                    item.source_tool == name and item.available for item in evidence
                ) else "✓"
                coverage_families.append(f"{mark} {name}")
            terminal = (
                DebugEventType.INVESTIGATION_FAILED
                if state.get("status") == InvestigationStatus.FAILED
                else DebugEventType.INVESTIGATION_COMPLETED
            )
            reason = stop_reason_for(state, no_dominant=self._no_dominant)
            total_ms = int((monotonic() - self._started) * 1000)
            self.record(
                terminal,
                stage="persist",
                summary=(
                    f"Investigation failed ({reason.value})"
                    if terminal == DebugEventType.INVESTIGATION_FAILED
                    else f"Investigation completed ({reason.value})"
                ),
                metadata={"stop_reason": reason.value},
                duration_ms=total_ms,
            )
            trigger = state.get("trigger")
            recommendation = state.get("recommendation")
            error = state.get("error")
            trace = InvestigationDebugTrace(
                investigation_id=state["investigation_id"],
                graph_version=state.get("graph_version"),
                provider=state.get("provider"),
                model=state.get("model"),
                stop_reason=reason,
                events=self._events,
                llm_proposed=self._proposed,
                backend_enforced=compact_conclusion(conclusion),
                validation_checks=self._checks,
                coverage=EvidenceCoverage(
                    initial_count=self._initial_count,
                    additional_requested=len(history),
                    available=sum(1 for item in evidence if item.available),
                    unavailable=sum(1 for item in evidence if not item.available),
                    contradictory=len(state.get("contradictions") or []),
                    iterations=state.get("iteration_count") or 0,
                    max_iterations=state.get("max_iterations") or 0,
                    families=coverage_families,
                ),
                usage=self._usage,
                wall_durations_ms=DebugDurations(
                    total=total_ms,
                    llm=self._llm_ms,
                    evidence=self._evidence_ms,
                ),
                trigger=redact(trigger.model_dump(mode="json") if trigger is not None else {}),
                recommendation=redact(
                    recommendation.model_dump(mode="json") if recommendation is not None else {}
                ),
                error=redact(error.model_dump(mode="json") if error is not None else None),
            )
            dump = trace.model_dump(mode="json")
            self.last_dump = dump
            return dump
        except Exception:
            logger.exception("Investigation debug trace assembly failed")
            return None


def create_debug_recorder(
    *,
    enabled: bool,
    investigation_id: str,
    model: str | None = None,
) -> InvestigationDebugSink:
    if not enabled:
        return NullDebugRecorder()
    return InvestigationDebugRecorder(investigation_id, model=model)


def consume_provider_metrics(provider: Any) -> dict[str, Any] | None:
    metrics = getattr(provider, "last_call_metrics", None)
    if isinstance(metrics, dict):
        try:
            provider.last_call_metrics = None
        except Exception:
            pass
        return metrics
    return None
