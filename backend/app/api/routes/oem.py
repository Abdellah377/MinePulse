from fastapi import APIRouter, HTTPException, Query

from app.api.deps import Ctx, DbSession
from app.oem.catalog import catalog_payload
from app.oem.connectivity import communication_delays, fleet_connectivity, parse_range, ping_diagram, ping_fleet
from app.oem import queries

router = APIRouter()


@router.get("/catalog")
def oem_catalog():
    return catalog_payload()


@router.get("/connectivity")
def oem_connectivity(
    session: DbSession,
    ctx: Ctx,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
):
    since, until = parse_range(from_, to, session, ctx=ctx)
    return {
        "from": since.isoformat(),
        "to": until.isoformat(),
        "rows": fleet_connectivity(session, since, until, site_id=ctx.site_id),
    }


@router.get("/connectivity/delays")
def oem_delays(
    session: DbSession,
    ctx: Ctx,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    min_delay_sec: float = 30,
):
    since, until = parse_range(from_, to, session, ctx=ctx)
    return {
        "from": since.isoformat(),
        "to": until.isoformat(),
        "minDelaySec": min_delay_sec,
        "rows": communication_delays(session, since, until, min_delay_sec, site_id=ctx.site_id),
    }


@router.get("/connectivity/ping")
def oem_ping_fleet(
    session: DbSession,
    ctx: Ctx,
    codes: str = "",
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
):
    since, until = parse_range(from_, to, session, ctx=ctx)
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    return {
        "from": since.isoformat(),
        "to": until.isoformat(),
        "rows": ping_fleet(session, code_list, since, until, site_id=ctx.site_id),
    }


@router.get("/connectivity/{code}/ping")
def oem_ping(
    code: str,
    session: DbSession,
    ctx: Ctx,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
):
    since, until = parse_range(from_, to, session, ctx=ctx)
    data = ping_diagram(session, code, since, until, site_id=ctx.site_id)
    if data.get("error") == "not_found":
        raise HTTPException(404, "Equipment not found")
    return data


@router.get("/equipment/{code}/telemetry")
def oem_telemetry(
    code: str,
    session: DbSession,
    ctx: Ctx,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    signals: str = "speed_kmh,fuel_level_pct",
):
    keys = [s.strip() for s in signals.split(",") if s.strip()][:16]
    data = queries.get_equipment_signal_history(session, code, from_, to, keys, site_id=ctx.site_id, ctx=ctx)
    if data.get("error") == "not_found":
        raise HTTPException(404, "Equipment not found")
    return data


@router.get("/equipment/{code}/tyres")
def oem_tyres(
    code: str,
    session: DbSession,
    ctx: Ctx,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    positions: str | None = None,
):
    pos = [p.strip() for p in positions.split(",")] if positions else None
    data = queries.get_tyre_history(session, code, from_, to, pos, site_id=ctx.site_id, ctx=ctx)
    if data.get("error") == "not_found":
        raise HTTPException(404, "Equipment not found")
    return data


@router.get("/diagnostic")
def oem_diagnostic(
    session: DbSession,
    ctx: Ctx,
    code: str | None = None,
    codes: str | None = None,
    params: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    group: str | None = None,
):
    return {"rows": queries.diagnostic_parameters(session, code, from_, to, group, codes, params, site_id=ctx.site_id, ctx=ctx)}


@router.get("/errors")
def oem_errors(
    session: DbSession,
    ctx: Ctx,
    code: str | None = None,
    codes: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    category: str | None = None,
):
    return {"rows": queries.error_codes(session, code, from_, to, severity, status, category, codes, site_id=ctx.site_id, ctx=ctx)}


@router.get("/maintenance-indicators")
def oem_maint(
    session: DbSession,
    ctx: Ctx,
    code: str | None = None,
    codes: str | None = None,
    params: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    group: str | None = None,
):
    return {"rows": queries.maintenance_indicators(session, code, from_, to, group, codes, params, site_id=ctx.site_id, ctx=ctx)}


@router.get("/anomalies")
def oem_anomalies(
    session: DbSession,
    ctx: Ctx,
    code: str | None = None,
    codes: str | None = None,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
):
    return {"rows": queries.sensor_anomalies(session, code, from_, to, codes, site_id=ctx.site_id, ctx=ctx)}
