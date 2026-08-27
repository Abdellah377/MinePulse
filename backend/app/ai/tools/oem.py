"""Thin adapters over existing OEM query services."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import EvidenceItem, EvidenceKind, EvidenceRequest, TelemetryMetricGroup
from app.ai.tools.operational import _evidence
from app.db.models import Equipment
from app.oem import queries
from app.oem.connectivity import fleet_connectivity, ping_diagram
from app.services.operational.context import OperationalContext


def _window(ctx: OperationalContext, request: EvidenceRequest):
    return request.start_time or ctx.shift_window_start, request.end_time or ctx.sim_now


TREND_DEFAULT_WINDOW_MINUTES = 15
TREND_MAX_WINDOW_MINUTES = 60
TREND_METRIC_GROUPS: dict[str, tuple[str, ...]] = {
    TelemetryMetricGroup.EQUIPMENT.value: (
        "engine_temp_c",
        "coolant_temp_c",
        "oil_pressure_kpa",
        "fuel_rate_lph",
        "engine_load_pct",
        "speed_kmh",
        "payload_t",
        "communication_quality",
    ),
    TelemetryMetricGroup.MECHANICAL.value: (
        "engine_temp_c",
        "coolant_temp_c",
        "oil_pressure_kpa",
        "engine_load_pct",
        "fuel_rate_lph",
        "speed_kmh",
    ),
    TelemetryMetricGroup.FUEL.value: (
        "fuel_rate_lph",
        "engine_load_pct",
        "speed_kmh",
        "payload_t",
        "engine_temp_c",
        "coolant_temp_c",
    ),
    TelemetryMetricGroup.CONNECTIVITY.value: (
        "communication_quality",
        "speed_kmh",
    ),
}


def _trend_window(ctx: OperationalContext, request: EvidenceRequest):
    until = max(min(request.end_time or ctx.sim_now, ctx.sim_now), ctx.shift_window_start)
    since = request.start_time or (until - timedelta(minutes=TREND_DEFAULT_WINDOW_MINUTES))
    since = max(since, ctx.shift_window_start, until - timedelta(minutes=TREND_MAX_WINDOW_MINUTES))
    return since, until


def telemetry_trends(
    session: Session,
    ctx: OperationalContext,
    request: EvidenceRequest,
) -> EvidenceItem:
    code = _equipment_code(session, ctx, request.equipment_id)
    if request.equipment_id is None or code is None:
        return _missing_equipment(
            ctx,
            request,
            "equipment_telemetry_trends",
            "get_equipment_signal_trends",
        )
    groups = request.parameters or [TelemetryMetricGroup.EQUIPMENT.value]
    invalid_groups = [group for group in groups if group not in TREND_METRIC_GROUPS]
    if invalid_groups:
        return _evidence(
            ctx,
            kind=EvidenceKind.DERIVED_METRIC,
            tool="equipment_telemetry_trends",
            service="app.oem.queries.get_equipment_signal_trends",
            metric="equipment_telemetry_trends",
            value=None,
            available=False,
            equipment_id=request.equipment_id,
            notes="Requested telemetry metric group is not in the approved catalog.",
            metadata={"unsupportedMetricGroups": invalid_groups},
        )
    metrics = list(
        dict.fromkeys(metric for group in groups for metric in TREND_METRIC_GROUPS[group])
    )
    since, until = _trend_window(ctx, request)
    result = queries.get_equipment_signal_trends(
        session,
        code,
        since.isoformat(),
        until.isoformat(),
        metrics,
        site_id=ctx.site_id,
        ctx=ctx,
    )
    if result.get("error") or result.get("empty"):
        return _evidence(
            ctx,
            kind=EvidenceKind.DERIVED_METRIC,
            tool="equipment_telemetry_trends",
            service="app.oem.queries.get_equipment_signal_trends",
            metric="equipment_telemetry_trends",
            value=None,
            available=False,
            equipment_id=request.equipment_id,
            source_record_ids=[f"equipment:{request.equipment_id}"],
            metadata={
                "windowStart": since,
                "windowEnd": until,
                "metricGroups": groups,
            },
            notes="No observed telemetry samples were available in the bounded incident window.",
        )
    pre_incident_count = max(
        (
            item["sampleCount"]
            for item in result.get("metrics", [])
            if item.get("lastObservedAt") and item["lastObservedAt"] <= until.isoformat()
        ),
        default=0,
    )
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="equipment_telemetry_trends",
        service="app.oem.queries.get_equipment_signal_trends",
        metric="equipment_telemetry_trends",
        value=result,
        equipment_id=request.equipment_id,
        source_record_ids=[f"equipment:{request.equipment_id}"],
        metadata={
            "windowStart": since,
            "windowEnd": until,
            "incidentTime": until,
            "metricGroups": groups,
            "metricCount": len(result.get("metrics", [])),
            "sourcePointCount": result.get("sourcePointCount", 0),
            "preIncidentSampleCount": pre_incident_count,
            "representativePointLimitPerMetric": queries.AI_TREND_MAX_REPRESENTATIVE_POINTS,
        },
        notes="Deterministic summaries and observed samples only; no interpolation or diagnosis.",
    )


def _equipment_code(session: Session, ctx: OperationalContext, equipment_id: int | None) -> str | None:
    if equipment_id is None:
        return None
    return session.scalar(
        select(Equipment.code).where(
            Equipment.site_id == ctx.site_id,
            Equipment.equipment_id == equipment_id,
            Equipment.active.is_(True),
        )
    )


def connectivity(session: Session, ctx: OperationalContext, request: EvidenceRequest) -> EvidenceItem:
    since, until = _window(ctx, request)
    rows = fleet_connectivity(session, since, until, site_id=ctx.site_id)
    if request.equipment_id is not None:
        code = _equipment_code(session, ctx, request.equipment_id)
        if code is None:
            return _evidence(
                ctx,
                kind=EvidenceKind.DERIVED_METRIC,
                tool="oem_connectivity",
                service="app.oem.connectivity.fleet_connectivity",
                metric="oem_connectivity",
                value=None,
                available=False,
                equipment_id=request.equipment_id,
                notes="Equipment is not active at the investigation site or does not exist.",
            )
        rows = [row for row in rows if row["code"] == code]
    else:
        code = None
    signal_history = None
    ping_history = None
    if code is not None:
        raw_history = queries.get_equipment_signal_history(
            session,
            code,
            since.isoformat(),
            until.isoformat(),
            ["communication_quality"],
            site_id=ctx.site_id,
            ctx=ctx,
        )
        signal_history = {
            **{key: value for key, value in raw_history.items() if key != "points"},
            "points": (raw_history.get("points") or [])[-60:],
        }
        ping_history = ping_diagram(
            session,
            code,
            since,
            until,
            site_id=ctx.site_id,
        )
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="oem_connectivity",
        service="app.oem.connectivity.fleet_connectivity",
        metric="oem_connectivity",
        value=rows,
        equipment_id=request.equipment_id,
        metadata={
            "windowStart": since,
            "windowEnd": until,
            "signalHistory": signal_history,
            "pingTimeline": ping_history,
        },
    )


def diagnostics(session: Session, ctx: OperationalContext, request: EvidenceRequest) -> EvidenceItem:
    code = _equipment_code(session, ctx, request.equipment_id)
    if request.equipment_id is not None and code is None:
        return _missing_equipment(ctx, request, "oem_diagnostics", "diagnostic_parameters")
    since, until = _window(ctx, request)
    params = request.parameters or [
        "engine_temp_c",
        "oil_pressure_kpa",
        "communication_quality",
        "fuel_rate_lph",
    ]
    rows = queries.diagnostic_parameters(
        session,
        code,
        since.isoformat(),
        until.isoformat(),
        None,
        None,
        ",".join(params),
        site_id=ctx.site_id,
        ctx=ctx,
    )
    history = None
    if code is not None:
        raw_history = queries.get_equipment_signal_history(
            session,
            code,
            since.isoformat(),
            until.isoformat(),
            params,
            site_id=ctx.site_id,
            ctx=ctx,
        )
        # Keep the LLM payload focused while preserving actual temporal order.
        history = {
            **{key: value for key, value in raw_history.items() if key != "points"},
            "points": (raw_history.get("points") or [])[-60:],
        }
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="oem_diagnostics",
        service="app.oem.queries.diagnostic_parameters",
        metric="oem_diagnostic_parameters",
        value=rows,
        equipment_id=request.equipment_id,
        metadata={
            "windowStart": since,
            "windowEnd": until,
            "parameters": params,
            "signalHistory": history,
        },
    )


def errors(session: Session, ctx: OperationalContext, request: EvidenceRequest) -> EvidenceItem:
    code = _equipment_code(session, ctx, request.equipment_id)
    if request.equipment_id is not None and code is None:
        return _missing_equipment(ctx, request, "oem_errors", "error_codes")
    since, until = _window(ctx, request)
    rows = queries.error_codes(
        session,
        code,
        since.isoformat(),
        until.isoformat(),
        None,
        None,
        None,
        None,
        site_id=ctx.site_id,
        ctx=ctx,
    )
    tyre_history = None
    if code is not None:
        raw_tyres = queries.get_tyre_history(
            session,
            code,
            since.isoformat(),
            until.isoformat(),
            None,
            site_id=ctx.site_id,
            ctx=ctx,
        )
        tyre_history = {
            **{key: value for key, value in raw_tyres.items() if key != "points"},
            "points": (raw_tyres.get("points") or [])[-60:],
        }
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="oem_errors",
        service="app.oem.queries.error_codes",
        metric="oem_error_codes",
        value=rows,
        equipment_id=request.equipment_id,
        metadata={
            "windowStart": since,
            "windowEnd": until,
            "tyreHistory": tyre_history,
        },
    )


def maintenance_indicators(
    session: Session,
    ctx: OperationalContext,
    request: EvidenceRequest,
) -> EvidenceItem:
    code = _equipment_code(session, ctx, request.equipment_id)
    if request.equipment_id is not None and code is None:
        return _missing_equipment(ctx, request, "oem_maintenance_indicators", "maintenance_indicators")
    since, until = _window(ctx, request)
    rows = queries.maintenance_indicators(
        session,
        code,
        since.isoformat(),
        until.isoformat(),
        None,
        None,
        ",".join(request.parameters) if request.parameters else None,
        site_id=ctx.site_id,
        ctx=ctx,
    )
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="oem_maintenance_indicators",
        service="app.oem.queries.maintenance_indicators",
        metric="oem_maintenance_indicators",
        value=rows,
        equipment_id=request.equipment_id,
        metadata={"windowStart": since, "windowEnd": until},
        notes="Threshold source is simulation/test where reported by the OEM service.",
    )


def _missing_equipment(
    ctx: OperationalContext,
    request: EvidenceRequest,
    tool: str,
    service_name: str,
) -> EvidenceItem:
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool=tool,
        service=f"app.oem.queries.{service_name}",
        metric=tool,
        value=None,
        available=False,
        equipment_id=request.equipment_id,
        notes="Equipment is not active at the investigation site or does not exist.",
    )
