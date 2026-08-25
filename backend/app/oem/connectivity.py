"""Connectivity derived from observation age vs simulation time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.enums import EquipmentState
from app.db.models import Equipment, EquipmentPosition, EquipmentState as EquipmentStateRow, EquipmentTelemetry
from app.mappers.enums import EQUIPMENT_STATE_TO_UI, EQUIPMENT_TYPE_TO_UI
from app.services.operational.clock import get_operational_now
from app.services.operational.equipment import latest_telemetry

MAX_RANGE = timedelta(days=7)


def sim_now() -> datetime:
    return get_operational_now()


def parse_range(
    from_s: str | None,
    to_s: str | None,
    session: Session | None = None,
    ctx=None,
) -> tuple[datetime, datetime]:
    now = sim_now()
    if ctx is not None:
        start, end = ctx.shift_window_start, ctx.sim_now
    elif session is not None:
        from app.services.operational.context import get_operational_context

        resolved = get_operational_context(session)
        start, end = resolved.shift_window_start, resolved.sim_now
        ctx = resolved
    else:
        start, end = now, now
    if from_s:
        start = datetime.fromisoformat(from_s.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    if to_s:
        end = datetime.fromisoformat(to_s.replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    if end < start:
        start, end = end, start
    if end - start > MAX_RANGE:
        start = end - MAX_RANGE
    return start, end


def _status(
    age_sec: float | None,
    state: EquipmentState | None,
    *,
    online_sec: float,
    disconnected_sec: float,
) -> str:
    if age_sec is None:
        return "unknown"
    if state == EquipmentState.NO_DATA or age_sec > disconnected_sec:
        return "disconnected"
    if age_sec > online_sec:
        return "delayed"
    return "online"


def fleet_connectivity(session: Session, since: datetime, until: datetime, *, site_id: int) -> list[dict]:
    from app.services.operational.settings import get_operational_settings

    ops = get_operational_settings(session)
    online_sec = float(ops.get("oem_online_sec", get_settings().oem_online_sec))
    disconnected_sec = float(ops.get("oem_disconnected_sec", get_settings().oem_disconnected_sec))
    equipment = session.scalars(
        select(Equipment).where(Equipment.active.is_(True), Equipment.site_id == site_id)
    ).all()
    tel_by_id = latest_telemetry(session, site_id)
    last_pos = dict(
        session.execute(
            select(EquipmentPosition.equipment_id, func.max(EquipmentPosition.ts))
            .join(Equipment, Equipment.equipment_id == EquipmentPosition.equipment_id)
            .where(Equipment.site_id == site_id)
            .group_by(EquipmentPosition.equipment_id)
        ).all()
    )

    out = []
    for eq in equipment:
        tel = tel_by_id.get(eq.equipment_id)
        tel_ts = tel.ts if tel else None
        pos_ts = last_pos.get(eq.equipment_id)
        tel_age = (until - tel_ts).total_seconds() if tel_ts else None
        pos_age = (until - pos_ts).total_seconds() if pos_ts else None
        status = _status(tel_age, eq.current_state, online_sec=online_sec, disconnected_sec=disconnected_sec)
        out.append(
            {
                "code": eq.code,
                "type": EQUIPMENT_TYPE_TO_UI.get(eq.type, eq.type.value.lower()),
                "model": eq.model,
                "commStatus": status,
                "lastTelemetry": tel_ts.isoformat() if tel_ts else None,
                "lastPosition": pos_ts.isoformat() if pos_ts else None,
                "telemetryDelaySec": round(tel_age, 1) if tel_age is not None else None,
                "gpsDelaySec": round(pos_age, 1) if pos_age is not None else None,
                "commQuality": float(tel.communication_quality) if tel and tel.communication_quality is not None else None,
                "speedKmh": float(tel.speed_kmh) if tel and tel.speed_kmh is not None else None,
                "fuelLevelPct": float(tel.fuel_level_pct) if tel and tel.fuel_level_pct is not None else None,
                "state": EQUIPMENT_STATE_TO_UI.get(eq.current_state, "indetermine"),
                "processedAt": None,
                "entity": None,
                "division": None,
                "externalId": None,
                "messageProcessing": None,
            }
        )
    return out


def communication_delays(
    session: Session, since: datetime, until: datetime, min_delay_sec: float, *, site_id: int
) -> list[dict]:
    rows = fleet_connectivity(session, since, until, site_id=site_id)
    ranked = []
    for r in rows:
        delay = r["telemetryDelaySec"]
        if delay is None:
            continue
        stats = _delay_stats(session, r["code"], since, until, site_id=site_id)
        current = delay
        mean_d = stats["meanDelaySec"] if stats["meanDelaySec"] is not None else current
        max_d = max(stats["maxDelaySec"] or 0, current)
        if current < min_delay_sec and r["commStatus"] == "online" and (max_d or 0) < min_delay_sec:
            continue
        ranked.append(
            {
                "code": r["code"],
                "lastData": r["lastTelemetry"],
                "lastTelemetry": r["lastTelemetry"],
                "lastPosition": r["lastPosition"],
                "currentDelaySec": current,
                "meanDelaySec": round(mean_d, 1) if mean_d is not None else None,
                "maxDelaySec": round(max_d, 1) if max_d else None,
                "incidentCount": stats["incidentCount"],
                "status": r["commStatus"],
            }
        )
    ranked.sort(key=lambda x: -(x["currentDelaySec"] or 0))
    return ranked


def _delay_stats(session: Session, code: str, since: datetime, until: datetime, *, site_id: int) -> dict:
    from app.services.operational.settings import get_operational_settings

    eq = session.scalar(select(Equipment).where(Equipment.code == code, Equipment.site_id == site_id))
    if not eq:
        return {"incidentCount": 0, "meanDelaySec": None, "maxDelaySec": None}
    ops = get_operational_settings(session)
    gap = float(ops.get("oem_disconnected_sec", get_settings().oem_disconnected_sec))
    times = list(
        session.scalars(
            select(EquipmentTelemetry.ts)
            .where(
                EquipmentTelemetry.equipment_id == eq.equipment_id,
                EquipmentTelemetry.ts >= since,
                EquipmentTelemetry.ts <= until,
            )
            .order_by(EquipmentTelemetry.ts)
        ).all()
    )
    if not times:
        span = (until - since).total_seconds()
        return {"incidentCount": 1, "meanDelaySec": span, "maxDelaySec": span}
    gaps: list[float] = []
    prev = since
    for ts in times:
        d = (ts - prev).total_seconds()
        if d > gap:
            gaps.append(d)
        prev = ts
    tail = (until - prev).total_seconds()
    if tail > gap:
        gaps.append(tail)
    return {
        "incidentCount": len(gaps),
        "meanDelaySec": (sum(gaps) / len(gaps)) if gaps else 0.0,
        "maxDelaySec": max(gaps) if gaps else 0.0,
    }


def ping_fleet(
    session: Session, codes: list[str], since: datetime, until: datetime, *, site_id: int | None = None
) -> list[dict]:
    out = []
    for code in codes:
        data = ping_diagram(session, code, since, until, site_id=site_id)
        if data.get("error") != "not_found":
            out.append(data)
    return out


def ping_diagram(session: Session, code: str, since: datetime, until: datetime, *, site_id: int | None = None) -> dict:
    from app.services.operational.settings import get_operational_settings

    filters = [Equipment.code == code]
    if site_id is not None:
        filters.append(Equipment.site_id == site_id)
    eq = session.scalar(select(Equipment).where(*filters))
    if not eq:
        return {"error": "not_found"}
    ops = get_operational_settings(session)
    gap = float(ops.get("oem_disconnected_sec", get_settings().oem_disconnected_sec))
    times = list(
        session.scalars(
            select(EquipmentTelemetry.ts)
            .where(
                EquipmentTelemetry.equipment_id == eq.equipment_id,
                EquipmentTelemetry.ts >= since,
                EquipmentTelemetry.ts <= until,
            )
            .order_by(EquipmentTelemetry.ts)
        ).all()
    )
    no_data = session.scalars(
        select(EquipmentStateRow).where(
            EquipmentStateRow.equipment_id == eq.equipment_id,
            EquipmentStateRow.state == EquipmentState.NO_DATA,
            EquipmentStateRow.start_time < until,
        )
    ).all()

    segments: list[dict] = []
    if not times:
        segments.append(
            {
                "id": "none",
                "status": "unknown",
                "start": int(since.timestamp() * 1000),
                "end": int(until.timestamp() * 1000),
            }
        )
    else:
        cursor = since
        for i, ts in enumerate(times):
            if (ts - cursor).total_seconds() > gap:
                segments.append(
                    {
                        "id": f"off-{i}",
                        "status": "disconnected",
                        "start": int(cursor.timestamp() * 1000),
                        "end": int(ts.timestamp() * 1000),
                    }
                )
            else:
                segments.append(
                    {
                        "id": f"on-{i}",
                        "status": "online",
                        "start": int(cursor.timestamp() * 1000),
                        "end": int(ts.timestamp() * 1000),
                    }
                )
            cursor = ts
        tail_status = "disconnected" if (until - cursor).total_seconds() > gap else "online"
        segments.append(
            {
                "id": "tail",
                "status": tail_status,
                "start": int(cursor.timestamp() * 1000),
                "end": int(until.timestamp() * 1000),
            }
        )

    for nd in no_data:
        end = nd.end_time or until
        segments.append(
            {
                "id": f"nodata-{nd.state_id}",
                "status": "disconnected",
                "start": int(max(nd.start_time, since).timestamp() * 1000),
                "end": int(min(end, until).timestamp() * 1000),
            }
        )

    merged = _merge_segments(segments, since, until)
    totals = {"online": 0.0, "disconnected": 0.0, "unknown": 0.0}
    for s in merged:
        dur = max(0, (s["end"] - s["start"]) / 1000)
        totals[s["status"]] = totals.get(s["status"], 0) + dur
    span = max(1.0, (until - since).total_seconds())
    connected = totals["online"]
    return {
        "code": eq.code,
        "from": since.isoformat(),
        "to": until.isoformat(),
        "segments": merged,
        "connectedSec": round(connected, 1),
        "disconnectedSec": round(totals["disconnected"], 1),
        "unknownSec": round(totals["unknown"], 1),
        "connectedPct": round(100.0 * connected / span, 1),
    }


def _merge_segments(segments: list[dict], since: datetime, until: datetime) -> list[dict]:
    if not segments:
        return []
    points = sorted(segments, key=lambda s: s["start"])
    merged = [points[0]]
    for s in points[1:]:
        last = merged[-1]
        if s["status"] == last["status"] and s["start"] <= last["end"] + 1000:
            last["end"] = max(last["end"], s["end"])
        else:
            merged.append(dict(s))
    return merged
