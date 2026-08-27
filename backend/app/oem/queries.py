"""OEM query services — reusable by API and future LangGraph tools."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Equipment, EquipmentTelemetry, SystemEvent, TyreTelemetry
from app.mappers.enums import EQUIPMENT_TYPE_TO_UI
from app.oem.catalog import (
    CATEGORY_LABELS,
    EVENT_TYPE_TO_CODE,
    SENSORS,
    SIM_ERROR_CODES,
    TELEMETRY_COLUMNS,
    TYRE_POSITIONS,
    is_available,
)
from app.oem.connectivity import parse_range
from app.oem.thresholds import SIM_THRESHOLDS, classify_value, expected_range

MAX_POINTS = 720
AI_TREND_MAX_METRICS = 8
AI_TREND_MAX_REPRESENTATIVE_POINTS = 8


def _equipment(session: Session, code: str, *, site_id: int) -> Equipment | None:
    return session.scalar(select(Equipment).where(Equipment.code == code, Equipment.site_id == site_id))


def _bucket_seconds(span: timedelta) -> int:
    sec = span.total_seconds()
    if sec <= 2 * 3600:
        return 10
    if sec <= 12 * 3600:
        return 60
    if sec <= 24 * 3600:
        return 300
    return 900


def get_equipment_signal_history(
    session: Session,
    code: str,
    from_s: str | None,
    to_s: str | None,
    signals: list[str],
    *,
    site_id: int,
    ctx=None,
) -> dict:
    eq = _equipment(session, code, site_id=site_id)
    if not eq:
        return {"error": "not_found"}
    since, until = parse_range(from_s, to_s, session, ctx=ctx)
    etype = eq.type.value
    valid = [s for s in signals if s in TELEMETRY_COLUMNS and is_available(s, etype)]
    unavailable = [s for s in signals if s not in valid]
    if not valid:
        return {
            "code": eq.code,
            "from": since.isoformat(),
            "to": until.isoformat(),
            "signals": [],
            "points": [],
            "unavailable": unavailable,
            "message": "Ce paramètre n'est pas disponible pour cet engin.",
        }
    bucket = _bucket_seconds(until - since)
    origin = since.timestamp()
    epoch = func.extract("epoch", EquipmentTelemetry.ts)
    trunc = func.to_timestamp(func.floor((epoch - origin) / bucket) * bucket + origin)
    cols = [getattr(EquipmentTelemetry, k) for k in valid]
    agg = [func.avg(c).label(c.key) for c in cols]
    agg += [func.min(c).label(f"{c.key}_min") for c in cols]
    agg += [func.max(c).label(f"{c.key}_max") for c in cols]
    rows = session.execute(
        select(trunc.label("bucket"), *agg)
        .where(
            EquipmentTelemetry.equipment_id == eq.equipment_id,
            EquipmentTelemetry.ts >= since,
            EquipmentTelemetry.ts <= until,
        )
        .group_by(trunc)
        .order_by(trunc)
        .limit(MAX_POINTS)
    ).all()
    points = []
    for r in rows:
        item = {"ts": r.bucket.isoformat() if r.bucket else None}
        for k in valid:
            v = getattr(r, k, None)
            item[k] = round(float(v), SENSORS[k].precision) if v is not None else None
            mn = getattr(r, f"{k}_min", None)
            mx = getattr(r, f"{k}_max", None)
            item[f"{k}_min"] = round(float(mn), SENSORS[k].precision) if mn is not None else None
            item[f"{k}_max"] = round(float(mx), SENSORS[k].precision) if mx is not None else None
        points.append(item)
    return {
        "code": eq.code,
        "type": EQUIPMENT_TYPE_TO_UI.get(eq.type, etype.lower()),
        "from": since.isoformat(),
        "to": until.isoformat(),
        "bucketSec": bucket,
        "signals": [
            {
                "key": k,
                "labelFr": SENSORS[k].label_fr,
                "unit": SENSORS[k].unit,
                "category": SENSORS[k].category,
            }
            for k in valid
        ],
        "points": points,
        "unavailable": unavailable,
        "empty": len(points) == 0,
    }


def _representative_samples(
    samples: list[dict],
    *,
    max_points: int = AI_TREND_MAX_REPRESENTATIVE_POINTS,
) -> list[dict]:
    """Deterministically retain endpoints and evenly spaced observed samples."""
    if max_points <= 1:
        return samples[:1]
    if len(samples) <= max_points:
        return samples
    indices = [round(index * (len(samples) - 1) / (max_points - 1)) for index in range(max_points)]
    return [samples[index] for index in dict.fromkeys(indices)]


def get_equipment_signal_trends(
    session: Session,
    code: str,
    from_s: str | None,
    to_s: str | None,
    signals: list[str],
    *,
    site_id: int,
    ctx=None,
    max_metrics: int = AI_TREND_MAX_METRICS,
    max_representative_points: int = AI_TREND_MAX_REPRESENTATIVE_POINTS,
) -> dict:
    """Compact observed telemetry history for investigation reasoning.

    This reuses the canonical site-scoped/bucketed OEM history query. It adds
    deterministic summaries and bounded representative points; it does not
    interpolate values or infer a diagnosis.
    """
    bounded_signals = list(dict.fromkeys(signals))[:max_metrics]
    history = get_equipment_signal_history(
        session,
        code,
        from_s,
        to_s,
        bounded_signals,
        site_id=site_id,
        ctx=ctx,
    )
    if history.get("error"):
        return history
    definitions = {item["key"]: item for item in history.get("signals", [])}
    points = history.get("points") or []
    trends = []
    for key in bounded_signals:
        definition = definitions.get(key)
        samples = [
            {"ts": point.get("ts"), "value": point.get(key)}
            for point in points
            if point.get("ts") is not None and point.get(key) is not None
        ]
        values = [float(sample["value"]) for sample in samples]
        if not values:
            trends.append(
                {
                    "metric": key,
                    "unit": definition.get("unit") if definition else None,
                    "sampleCount": 0,
                    "firstObservedAt": None,
                    "lastObservedAt": None,
                    "firstValue": None,
                    "lastValue": None,
                    "min": None,
                    "max": None,
                    "mean": None,
                    "absoluteChange": None,
                    "percentageChange": None,
                    "direction": "insufficient_data",
                    "missingData": True,
                    "representativeSamples": [],
                }
            )
            continue
        precision = SENSORS[key].precision
        first = values[0]
        last = values[-1]
        change = last - first
        stable_tolerance = max(10 ** (-precision), abs(first) * 0.02)
        direction = "stable"
        if change > stable_tolerance:
            direction = "rising"
        elif change < -stable_tolerance:
            direction = "falling"
        percentage_change = (change / abs(first) * 100.0) if first != 0 else None
        trends.append(
            {
                "metric": key,
                "unit": definition.get("unit") if definition else SENSORS[key].unit,
                "sampleCount": len(values),
                "firstObservedAt": samples[0]["ts"],
                "lastObservedAt": samples[-1]["ts"],
                "firstValue": round(first, precision),
                "lastValue": round(last, precision),
                "min": round(min(values), precision),
                "max": round(max(values), precision),
                "mean": round(sum(values) / len(values), precision),
                "absoluteChange": round(change, precision),
                "percentageChange": (
                    round(percentage_change, 1) if percentage_change is not None else None
                ),
                "direction": direction,
                "missingData": False,
                "representativeSamples": _representative_samples(
                    samples,
                    max_points=max_representative_points,
                ),
            }
        )
    return {
        "code": history.get("code"),
        "type": history.get("type"),
        "from": history.get("from"),
        "to": history.get("to"),
        "bucketSec": history.get("bucketSec"),
        "metrics": trends,
        "unavailable": history.get("unavailable", []),
        "sourcePointCount": len(points),
        "empty": not any(item["sampleCount"] for item in trends),
    }


def get_tyre_history(
    session: Session,
    code: str,
    from_s: str | None,
    to_s: str | None,
    positions: list[str] | None,
    *,
    site_id: int,
    ctx=None,
) -> dict:
    eq = _equipment(session, code, site_id=site_id)
    if not eq:
        return {"error": "not_found"}
    if eq.type.value != "HAUL_TRUCK":
        return {"code": eq.code, "message": "Aucune donnée pneu disponible pour cet engin.", "series": []}
    since, until = parse_range(from_s, to_s, session, ctx=ctx)
    wanted = [p for p in (positions or list(TYRE_POSITIONS)) if p in TYRE_POSITIONS]
    bucket = _bucket_seconds(until - since)
    origin = since.timestamp()
    epoch = func.extract("epoch", TyreTelemetry.ts)
    trunc = func.to_timestamp(func.floor((epoch - origin) / bucket) * bucket + origin)
    rows = session.execute(
        select(
            trunc.label("bucket"),
            TyreTelemetry.position,
            func.avg(TyreTelemetry.pressure_kpa).label("pressure"),
            func.avg(TyreTelemetry.temperature_c).label("temp"),
        )
        .where(
            TyreTelemetry.equipment_id == eq.equipment_id,
            TyreTelemetry.ts >= since,
            TyreTelemetry.ts <= until,
            TyreTelemetry.position.in_(wanted),
        )
        .group_by(trunc, TyreTelemetry.position)
        .order_by(trunc)
        .limit(MAX_POINTS * 6)
    ).all()
    if not rows:
        return {
            "code": eq.code,
            "from": since.isoformat(),
            "to": until.isoformat(),
            "message": "Aucune donnée pneu disponible pour cet engin.",
            "positions": [{"code": p, "labelFr": TYRE_POSITIONS[p]} for p in wanted],
            "points": [],
        }
    by_ts: dict[str, dict] = {}
    for r in rows:
        key = r.bucket.isoformat() if r.bucket else ""
        item = by_ts.setdefault(key, {"ts": key})
        item[f"{r.position}_pressure"] = round(float(r.pressure), 1) if r.pressure is not None else None
        item[f"{r.position}_temp"] = round(float(r.temp), 1) if r.temp is not None else None
    return {
        "code": eq.code,
        "from": since.isoformat(),
        "to": until.isoformat(),
        "bucketSec": bucket,
        "positions": [{"code": p, "labelFr": TYRE_POSITIONS[p]} for p in wanted],
        "points": list(by_ts.values()),
        "message": None,
    }


def _csv_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [x.strip() for x in value.split(",") if x.strip()]
    return items or None


def diagnostic_parameters(
    session: Session,
    code: str | None,
    from_s: str | None,
    to_s: str | None,
    group: str | None,
    codes: str | None = None,
    params: str | None = None,
    *,
    site_id: int,
    ctx=None,
) -> list[dict]:
    since, until = parse_range(from_s, to_s, session, ctx=ctx)
    q = select(Equipment).where(Equipment.active.is_(True), Equipment.site_id == site_id)
    wanted = _csv_list(codes) or ([code] if code else None)
    if wanted:
        q = q.where(Equipment.code.in_(wanted))
    equipment = session.scalars(q).all()
    out: list[dict] = []
    param_filter = _csv_list(params)
    keys = [
        k
        for k, s in SENSORS.items()
        if s.source == "telemetry"
        and (not group or s.category == group)
        and (not param_filter or k in param_filter)
    ]
    for eq in equipment:
        etype = eq.type.value
        avail = [k for k in keys if is_available(k, etype)]
        if not avail:
            continue
        cols = [getattr(EquipmentTelemetry, k) for k in avail]
        aggs = []
        for c in cols:
            aggs.extend(
                [
                    func.min(c).label(f"{c.key}_min"),
                    func.avg(c).label(f"{c.key}_avg"),
                    func.max(c).label(f"{c.key}_max"),
                ]
            )
        row = session.execute(
            select(*aggs).where(
                EquipmentTelemetry.equipment_id == eq.equipment_id,
                EquipmentTelemetry.ts >= since,
                EquipmentTelemetry.ts <= until,
            )
        ).one()
        last = session.scalar(
            select(EquipmentTelemetry)
            .where(EquipmentTelemetry.equipment_id == eq.equipment_id)
            .order_by(EquipmentTelemetry.ts.desc())
            .limit(1)
        )
        for k in avail:
            s = SENSORS[k]
            mn = getattr(row, f"{k}_min", None)
            avg = getattr(row, f"{k}_avg", None)
            mx = getattr(row, f"{k}_max", None)
            if mn is None and avg is None and mx is None:
                continue
            last_v = getattr(last, k, None) if last else None
            status = classify_value(k, float(last_v)) if last_v is not None else None
            out.append(
                {
                    "code": eq.code,
                    "parameter": s.label_fr,
                    "parameterKey": k,
                    "ts": last.ts.isoformat() if last else None,
                    "min": round(float(mn), s.precision) if mn is not None else None,
                    "avg": round(float(avg), s.precision) if avg is not None else None,
                    "max": round(float(mx), s.precision) if mx is not None else None,
                    "unit": s.unit,
                    "sensorStatus": (status or "ok") if last_v is not None and k in SIM_THRESHOLDS else None,
                    "sensorWorking": None if last_v is None or k not in SIM_THRESHOLDS else "Oui" if status is None else "Alarme",
                    "thresholdSource": SIM_THRESHOLDS[k].source if k in SIM_THRESHOLDS else None,
                    "category": s.category,
                    "categoryLabel": CATEGORY_LABELS.get(s.category, s.category),
                }
            )
    return out


def error_codes(
    session: Session,
    code: str | None,
    from_s: str | None,
    to_s: str | None,
    severity: str | None,
    status: str | None,
    category: str | None,
    codes: str | None = None,
    *,
    site_id: int,
    ctx=None,
) -> list[dict]:
    since, until = parse_range(from_s, to_s, session, ctx=ctx)
    sim_types = list(EVENT_TYPE_TO_CODE.keys())
    scoped_equipment = select(Equipment.equipment_id).where(Equipment.site_id == site_id)
    q = select(SystemEvent).where(
        SystemEvent.ts >= since,
        SystemEvent.ts <= until,
        SystemEvent.equipment_id.in_(scoped_equipment),
    )
    wanted = _csv_list(codes) or ([code] if code else None)
    if wanted:
        eqs = session.scalars(
            select(Equipment).where(Equipment.site_id == site_id, Equipment.code.in_(wanted))
        ).all()
        if not eqs:
            return []
        q = q.where(SystemEvent.equipment_id.in_([e.equipment_id for e in eqs]))
    q = q.where(
        or_(
            SystemEvent.event_type.in_(sim_types),
            SystemEvent.event_type.like("SIM-%"),
        )
    )
    rows = session.scalars(q.order_by(SystemEvent.ts.desc()).limit(2000)).all()
    grouped: dict[str, dict] = {}
    code_by_id: dict[int, str] = {}
    if rows:
        ids = {r.equipment_id for r in rows if r.equipment_id}
        if ids:
            for e in session.scalars(
                select(Equipment).where(Equipment.site_id == site_id, Equipment.equipment_id.in_(ids))
            ):
                code_by_id[e.equipment_id] = e.code
    for r in rows:
        mapped = EVENT_TYPE_TO_CODE.get(r.event_type, r.event_type if r.event_type.startswith("SIM-") else None)
        if not mapped:
            continue
        meta = SIM_ERROR_CODES.get(mapped, {"category": "moteur", "severity": "INFO", "label": mapped})
        raw = r.raw_data or {}
        sev = str(raw.get("severity") or meta["severity"]).upper()
        cat = str(raw.get("category") or meta["category"])
        if severity and sev.lower() != severity.lower():
            continue
        if category and cat != category:
            continue
        st = str(raw.get("status") or "ACTIVE")
        if status and st.lower() != status.lower():
            continue
        eq_code = code_by_id.get(r.equipment_id or 0, "—")
        key = f"{eq_code}|{mapped}"
        g = grouped.get(key)
        if not g:
            grouped[key] = {
                "ts": r.ts.isoformat(),
                "code": eq_code,
                "errorCode": mapped,
                "catalogSource": "simulation/test" if mapped in SIM_ERROR_CODES else None,
                "category": cat,
                "description": meta["label"],
                "severity": sev,
                "firstOccurrence": r.ts.isoformat(),
                "lastOccurrence": r.ts.isoformat(),
                "endTime": None,
                "occurrences": 1,
                "status": st,
            }
        else:
            g["occurrences"] += 1
            if r.ts.isoformat() > g["lastOccurrence"]:
                g["lastOccurrence"] = r.ts.isoformat()
                g["ts"] = r.ts.isoformat()
            if r.ts.isoformat() < g["firstOccurrence"]:
                g["firstOccurrence"] = r.ts.isoformat()
    return sorted(grouped.values(), key=lambda x: x["lastOccurrence"], reverse=True)


def maintenance_indicators(
    session: Session,
    code: str | None,
    from_s: str | None,
    to_s: str | None,
    group: str | None,
    codes: str | None = None,
    params: str | None = None,
    *,
    site_id: int,
    ctx=None,
) -> list[dict]:
    since, until = parse_range(from_s, to_s, session, ctx=ctx)
    q = select(Equipment).where(Equipment.active.is_(True), Equipment.site_id == site_id)
    wanted = _csv_list(codes) or ([code] if code else None)
    if wanted:
        q = q.where(Equipment.code.in_(wanted))
    equipment = session.scalars(q).all()
    out = []
    param_filter = _csv_list(params)
    keys = [
        k
        for k, s in SENSORS.items()
        if s.source == "telemetry"
        and k in SIM_THRESHOLDS
        and (not group or s.category == group)
        and (not param_filter or k in param_filter)
    ]
    for eq in equipment:
        etype = eq.type.value
        for k in keys:
            if not is_available(k, etype):
                continue
            col = getattr(EquipmentTelemetry, k)
            th = SIM_THRESHOLDS[k]
            filters = [
                EquipmentTelemetry.equipment_id == eq.equipment_id,
                EquipmentTelemetry.ts >= since,
                EquipmentTelemetry.ts <= until,
                col.is_not(None),
            ]
            stats = session.execute(
                select(func.min(col), func.avg(col), func.max(col), func.count()).where(and_(*filters))
            ).one()
            mn, avg, mx, n = stats
            if not n:
                continue
            alarm_max_red = 0
            alarm_max_yellow = 0
            alarm_min_red = 0
            alarm_min_yellow = 0
            if th.crit_high is not None:
                alarm_max_red = session.scalar(select(func.count()).where(and_(*filters), col >= th.crit_high)) or 0
            if th.warn_high is not None:
                if th.crit_high is not None:
                    alarm_max_yellow = (
                        session.scalar(
                            select(func.count()).where(and_(*filters), col >= th.warn_high, col < th.crit_high)
                        )
                        or 0
                    )
                else:
                    alarm_max_yellow = session.scalar(select(func.count()).where(and_(*filters), col >= th.warn_high)) or 0
            if th.crit_low is not None:
                alarm_min_red = session.scalar(select(func.count()).where(and_(*filters), col <= th.crit_low)) or 0
            if th.warn_low is not None:
                if th.crit_low is not None:
                    alarm_min_yellow = (
                        session.scalar(
                            select(func.count()).where(and_(*filters), col <= th.warn_low, col > th.crit_low)
                        )
                        or 0
                    )
                else:
                    alarm_min_yellow = session.scalar(select(func.count()).where(and_(*filters), col <= th.warn_low)) or 0
            last = session.scalar(
                select(col)
                .where(EquipmentTelemetry.equipment_id == eq.equipment_id, col.is_not(None))
                .order_by(EquipmentTelemetry.ts.desc())
                .limit(1)
            )
            s = SENSORS[k]
            span_sec = max(1.0, (until - since).total_seconds())
            span_h = span_sec / 3600
            out.append(
                {
                    "code": eq.code,
                    "parameter": s.label_fr,
                    "parameterKey": k,
                    "unit": s.unit,
                    "avg": round(float(avg), s.precision) if avg is not None else None,
                    "min": round(float(mn), s.precision) if mn is not None else None,
                    "max": round(float(mx), s.precision) if mx is not None else None,
                    "belowThreshold": int(alarm_min_red + alarm_min_yellow),
                    "aboveThreshold": int(alarm_max_red + alarm_max_yellow),
                    "alarmMaxRed": int(alarm_max_red),
                    "alarmMaxYellow": int(alarm_max_yellow),
                    "alarmMinRed": int(alarm_min_red),
                    "alarmMinYellow": int(alarm_min_yellow),
                    "sampleRatePerH": round(int(n) / span_h, 1),
                    "reportIntervalSec": round(span_sec / max(1, int(n))),
                    "lastValue": round(float(last), s.precision) if last is not None else None,
                    "thresholdSource": "simulation/test",
                }
            )
    return out


def sensor_anomalies(
    session: Session,
    code: str | None,
    from_s: str | None,
    to_s: str | None,
    codes: str | None = None,
    *,
    site_id: int,
    ctx=None,
) -> list[dict]:
    since, until = parse_range(from_s, to_s, session, ctx=ctx)
    scoped_equipment = select(Equipment.equipment_id).where(Equipment.site_id == site_id)
    q = select(SystemEvent).where(
        SystemEvent.ts >= since,
        SystemEvent.ts <= until,
        SystemEvent.equipment_id.in_(scoped_equipment),
        or_(
            SystemEvent.event_type.like("SIM-%"),
            SystemEvent.event_type.in_(list(EVENT_TYPE_TO_CODE.keys())),
        ),
    )
    wanted = _csv_list(codes) or ([code] if code else None)
    if wanted:
        eqs = session.scalars(
            select(Equipment).where(Equipment.site_id == site_id, Equipment.code.in_(wanted))
        ).all()
        if not eqs:
            return []
        q = q.where(SystemEvent.equipment_id.in_([e.equipment_id for e in eqs]))
    rows = session.scalars(q.order_by(SystemEvent.ts.desc()).limit(1000)).all()
    code_by_id: dict[int, str] = {}
    ids = {r.equipment_id for r in rows if r.equipment_id}
    if ids:
        for e in session.scalars(
            select(Equipment).where(Equipment.site_id == site_id, Equipment.equipment_id.in_(ids))
        ):
            code_by_id[e.equipment_id] = e.code
    out = []
    for r in rows:
        raw = r.raw_data or {}
        mapped = EVENT_TYPE_TO_CODE.get(r.event_type, r.event_type)
        meta = SIM_ERROR_CODES.get(mapped, {})
        param = raw.get("parameter") or mapped
        sdef = SENSORS.get(param)
        lo = raw.get("expectedLow")
        hi = raw.get("expectedHigh")
        if lo is None and hi is None and param:
            lo, hi = expected_range(param)
        rng = "—"
        if lo is not None and hi is not None:
            rng = f"{lo} – {hi}"
        elif lo is not None:
            rng = f"> {lo}"
        elif hi is not None:
            rng = f"< {hi}"
        out.append(
            {
                "ts": r.ts.isoformat(),
                "code": code_by_id.get(r.equipment_id or 0, "—"),
                "parameter": sdef.label_fr if sdef else meta.get("label", param),
                "parameterKey": param,
                "value": raw.get("value"),
                "expectedRange": rng,
                "thresholdSource": "source event" if raw.get("expectedLow") is not None or raw.get("expectedHigh") is not None else SIM_THRESHOLDS[param].source if param in SIM_THRESHOLDS else None,
                "catalogSource": "simulation/test" if mapped in SIM_ERROR_CODES else None,
                "anomalyType": meta.get("label", mapped),
                "severity": raw.get("severity") or meta.get("severity", "WARNING"),
                "durationSec": raw.get("durationSec"),
                "status": raw.get("status") or "ACTIVE",
                "position": raw.get("position"),
            }
        )
    return out
