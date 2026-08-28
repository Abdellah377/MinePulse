"""Controlled evidence request dispatcher; there is no arbitrary SQL/tool path."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
from time import monotonic
from uuid import uuid4

from sqlalchemy.orm import Session

from app.ai.contracts import (
    EvidenceItem,
    EvidenceKind,
    EvidenceRequest,
    EvidenceRequestType,
    EvidenceStatus,
    InvestigationTrigger,
    TelemetryMetricGroup,
    TriggerType,
)
from app.ai.debug import DebugEventType, InvestigationDebugSink, NullDebugRecorder
from app.ai.tools import oem, operational
from app.services.operational.context import OperationalContext

logger = logging.getLogger(__name__)


class EvidenceToolRegistry:
    def __init__(self, session: Session, debug: InvestigationDebugSink | None = None):
        self.session = session
        self.debug = debug or NullDebugRecorder()

    def gather_initial(
        self,
        ctx: OperationalContext,
        trigger: InvestigationTrigger,
    ) -> list[EvidenceItem]:
        trigger_text = json.dumps(trigger.payload, ensure_ascii=False).casefold()
        congestion_related = trigger.trigger_type == TriggerType.CONGESTION_RISK or any(
            term in trigger_text for term in ("wait", "attente", "congestion", "idle", "queue")
        )
        production_related = trigger.trigger_type == TriggerType.PRODUCTION_DEVIATION or any(
            term in trigger_text for term in ("production", "tonnage", "shortfall")
        )
        tools: list[tuple[str, Callable[[], EvidenceItem]]] = [
            ("operational_context", lambda: operational.context_evidence(ctx)),
            ("shift_production", lambda: operational.shift_production(self.session, ctx)),
            (
                "fleet_snapshot",
                lambda: operational.fleet_snapshot(
                    self.session,
                    ctx,
                    equipment_id=(
                        trigger.equipment_id
                        if trigger.trigger_type
                        in {TriggerType.EQUIPMENT_ANOMALY, TriggerType.MAINTENANCE_RISK}
                        else None
                    ),
                ),
            ),
            ("cycle_performance", lambda: operational.cycle_performance(self.session, ctx)),
            ("downtime", lambda: operational.downtime(self.session, ctx)),
            ("site_alerts", lambda: operational.site_alerts(self.session, ctx)),
        ]
        if congestion_related or production_related:
            tools.append(
                (
                    "loading_context",
                    lambda: operational.loading_context(
                        self.session,
                        ctx,
                        equipment_id=trigger.equipment_id,
                        zone_id=trigger.zone_id,
                    ),
                )
            )
        if congestion_related and trigger.equipment_id is not None:
            tools.append(
                (
                    "equipment_timeline",
                    lambda: operational.equipment_timeline(
                        self.session, ctx, equipment_id=trigger.equipment_id
                    ),
                )
            )
        if trigger.equipment_id is not None:
            if trigger.trigger_type == TriggerType.CONNECTIVITY_ISSUE or any(
                term in trigger_text for term in ("communication", "connectivity", "telemetry")
            ):
                group = TelemetryMetricGroup.CONNECTIVITY
            elif any(term in trigger_text for term in ("fuel", "carburant", "consommation")):
                group = TelemetryMetricGroup.FUEL
            elif trigger.trigger_type in {TriggerType.EQUIPMENT_ANOMALY, TriggerType.MAINTENANCE_RISK}:
                group = TelemetryMetricGroup.MECHANICAL
            else:
                group = TelemetryMetricGroup.EQUIPMENT
            trend_request = EvidenceRequest(
                request_type=EvidenceRequestType.EQUIPMENT_TELEMETRY_TRENDS,
                equipment_id=trigger.equipment_id,
                end_time=trigger.occurred_at,
                parameters=[group.value],
                reason="Collect bounded telemetry trends preceding the investigated incident.",
            )
            tools.append(
                (
                    "equipment_telemetry_trends",
                    lambda: oem.telemetry_trends(self.session, ctx, trend_request),
                )
            )
        return [self._safe_call(ctx, name, call) for name, call in tools]

    def gather_requested(
        self,
        ctx: OperationalContext,
        requests: list[EvidenceRequest],
    ) -> list[EvidenceItem]:
        return [self.dispatch(ctx, request) for request in requests]

    def dispatch(self, ctx: OperationalContext, request: EvidenceRequest) -> EvidenceItem:
        request_type = (
            request.request_type.value
            if isinstance(request.request_type, EvidenceRequestType)
            else str(request.request_type)
        )
        handlers: dict[str, Callable[[], EvidenceItem]] = {
            EvidenceRequestType.SHIFT_PRODUCTION.value: lambda: operational.shift_production(self.session, ctx),
            EvidenceRequestType.FLEET_SNAPSHOT.value: lambda: operational.fleet_snapshot(
                self.session, ctx, equipment_id=request.equipment_id
            ),
            EvidenceRequestType.CYCLE_PERFORMANCE.value: lambda: operational.cycle_performance(self.session, ctx),
            EvidenceRequestType.DOWNTIME.value: lambda: operational.downtime(self.session, ctx),
            EvidenceRequestType.SITE_ALERTS.value: lambda: operational.site_alerts(self.session, ctx),
            EvidenceRequestType.ASSIGNMENTS.value: lambda: operational.assignments(
                self.session, ctx, equipment_id=request.equipment_id
            ),
            EvidenceRequestType.EQUIPMENT_TIMELINE.value: lambda: operational.equipment_timeline(
                self.session, ctx, equipment_id=request.equipment_id
            ),
            EvidenceRequestType.LOADING_CONTEXT.value: lambda: operational.loading_context(
                self.session,
                ctx,
                equipment_id=request.equipment_id,
                zone_id=request.zone_id,
            ),
            EvidenceRequestType.ZONE_CONTEXT.value: lambda: operational.zone_context(
                self.session, ctx, zone_id=request.zone_id
            ),
            EvidenceRequestType.OEM_CONNECTIVITY.value: lambda: oem.connectivity(self.session, ctx, request),
            EvidenceRequestType.OEM_DIAGNOSTICS.value: lambda: oem.diagnostics(self.session, ctx, request),
            EvidenceRequestType.OEM_ERRORS.value: lambda: oem.errors(self.session, ctx, request),
            EvidenceRequestType.OEM_MAINTENANCE_INDICATORS.value: lambda: oem.maintenance_indicators(
                self.session, ctx, request
            ),
            EvidenceRequestType.EQUIPMENT_TELEMETRY_TRENDS.value: lambda: oem.telemetry_trends(
                self.session, ctx, request
            ),
        }
        handler = handlers.get(request_type)
        if handler is None:
            return EvidenceItem(
                kind=EvidenceKind.FACT,
                source_tool="unsupported_evidence_request",
                source_service="app.ai.tools.registry.EvidenceToolRegistry.dispatch",
                metric=request_type,
                value=None,
                available=False,
                status=EvidenceStatus.UNSUPPORTED,
                site_id=ctx.site_id,
                shift_id=ctx.shift_id,
                observed_at=ctx.sim_now,
                metadata={"requestId": request.request_id},
                notes="The request type is not in the approved MinePulse evidence catalog.",
            )
        item = self._safe_call(
            ctx,
            request_type.lower(),
            handler,
            request_id=request.request_id,
        )
        item.metadata = {**item.metadata, "requestId": request.request_id, "requestReason": request.reason}
        return item

    def _safe_call(
        self,
        ctx: OperationalContext,
        tool_name: str,
        call: Callable[[], EvidenceItem],
        *,
        request_id: str | None = None,
    ) -> EvidenceItem:
        started = monotonic()
        try:
            item = call()
        except Exception as exc:
            duration_ms = int((monotonic() - started) * 1000)
            self._record_tool(tool_name, None, duration_ms, request_id=request_id, outcome="error")
            error_reference = f"ai-tool-{uuid4()}"
            logger.exception(
                "AI evidence service failed",
                extra={
                    "error_reference": error_reference,
                    "tool_name": tool_name,
                    "request_id": request_id,
                    "site_id": ctx.site_id,
                    "shift_id": ctx.shift_id,
                },
            )
            return EvidenceItem(
                kind=EvidenceKind.FACT,
                source_tool=tool_name,
                source_service="approved MinePulse service adapter",
                metric=tool_name,
                value=None,
                available=False,
                status=EvidenceStatus.ERROR,
                site_id=ctx.site_id,
                shift_id=ctx.shift_id,
                observed_at=ctx.sim_now,
                metadata={
                    "errorReference": error_reference,
                    "failureCategory": "SERVICE_ERROR",
                    **({"requestId": request_id} if request_id else {}),
                },
                notes="Approved evidence lookup failed; value is unavailable.",
            )
        duration_ms = int((monotonic() - started) * 1000)
        status = getattr(item.status, "value", item.status)
        outcome = "available" if item.available else (status or "unavailable")
        self._record_tool(
            tool_name,
            item,
            duration_ms,
            request_id=request_id,
            outcome=str(outcome),
        )
        return item

    def _record_tool(
        self,
        tool_name: str,
        item: EvidenceItem | None,
        duration_ms: int,
        *,
        request_id: str | None,
        outcome: str,
    ) -> None:
        try:
            self.debug.add_evidence_duration(duration_ms)
            self.debug.record(
                DebugEventType.TOOL_COMPLETED,
                stage="evidence",
                summary=f"Tool {tool_name}: {outcome}",
                duration_ms=duration_ms,
                metadata={
                    "tool_name": tool_name,
                    "outcome": outcome,
                    "available": bool(item.available) if item is not None else False,
                    "evidence_id": item.evidence_id if item is not None else None,
                    "request_id": request_id,
                    "source_tool": item.source_tool if item is not None else tool_name,
                    "status": getattr(item.status, "value", item.status) if item is not None else "ERROR",
                },
            )
        except Exception:
            logger.exception("Investigation debug tool record failed")
