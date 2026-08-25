"""Thin adapters over existing OEM query services."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import EvidenceItem, EvidenceKind, EvidenceRequest
from app.ai.tools.operational import _evidence
from app.db.models import Equipment
from app.oem import queries
from app.oem.connectivity import fleet_connectivity
from app.services.operational.context import OperationalContext


def _window(ctx: OperationalContext, request: EvidenceRequest):
    return request.start_time or ctx.shift_window_start, request.end_time or ctx.sim_now


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
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="oem_connectivity",
        service="app.oem.connectivity.fleet_connectivity",
        metric="oem_connectivity",
        value=rows,
        equipment_id=request.equipment_id,
        metadata={"windowStart": since, "windowEnd": until},
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
    return _evidence(
        ctx,
        kind=EvidenceKind.DERIVED_METRIC,
        tool="oem_diagnostics",
        service="app.oem.queries.diagnostic_parameters",
        metric="oem_diagnostic_parameters",
        value=rows,
        equipment_id=request.equipment_id,
        metadata={"windowStart": since, "windowEnd": until, "parameters": params},
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
    return _evidence(
        ctx,
        kind=EvidenceKind.FACT,
        tool="oem_errors",
        service="app.oem.queries.error_codes",
        metric="oem_error_codes",
        value=rows,
        equipment_id=request.equipment_id,
        metadata={"windowStart": since, "windowEnd": until},
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
