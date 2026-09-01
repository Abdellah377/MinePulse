"""Production targets and actuals summary."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ProductionActual, ProductionTarget, Shift
from app.services.operational.context import OperationalContext


def _shift_duration_hours(shift: Shift) -> float | None:
    start_m = shift.start_time.hour * 60 + shift.start_time.minute
    end_m = shift.end_time.hour * 60 + shift.end_time.minute
    if end_m <= start_m:
        end_m += 24 * 60
    return max(0.5, (end_m - start_m) / 60.0)


def shiftly_attainment(tonnage: float, target: float | None) -> dict:
    """Attainment fields for a shift row. Missing/zero target → nulls, never 0%."""
    if target is None or target <= 0:
        return {"attainmentPct": None, "gapTons": None, "gapPct": None}
    gap = target - tonnage
    return {
        "attainmentPct": round((tonnage / target) * 100, 1),
        "gapTons": round(gap, 1),
        "gapPct": round((gap / target) * 100, 1),
    }


def _target_cycle_min(target_row: ProductionTarget | None) -> float | None:
    if not target_row or not target_row.metadata_:
        return None
    raw = target_row.metadata_.get("target_cycle_min")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _production_for_one_shift(session: Session, shift: Shift) -> dict:
    shift_id = shift.shift_id
    target_row = session.scalar(select(ProductionTarget).where(ProductionTarget.shift_id == shift_id))
    target: float | None = (
        float(target_row.target_tonnes) if target_row and target_row.target_tonnes is not None else None
    )
    duration_h = _shift_duration_hours(shift)
    hourly_target: float | None = (target / duration_h) if target is not None and duration_h else None

    rows = session.execute(
        select(
            func.date_trunc("hour", ProductionActual.ts).label("hour"),
            func.coalesce(func.sum(ProductionActual.tonnes), 0),
        )
        .where(ProductionActual.shift_id == shift_id)
        .group_by("hour")
        .order_by("hour")
    ).all()

    hourly: list[dict] = []
    total = 0.0
    for hour, tonnes in rows:
        t = float(tonnes)
        total += t
        hourly.append(
            {
                "hour": hour,
                "label": hour.strftime("%Hh") if hour else "?",
                "tonnage": t,
                "target": hourly_target,
            }
        )

    shiftly_entry: dict = {
        "label": shift.name,
        "tonnage": total,
        "target": target,
    }
    cycle_min = _target_cycle_min(target_row)
    if cycle_min is not None:
        shiftly_entry["targetCycleMin"] = cycle_min
    shiftly_entry.update(shiftly_attainment(total, target))

    return {
        "shiftly": [shiftly_entry],
        "hourly": hourly,
        "daily": [{"label": shift.shift_date.isoformat(), "tonnage": total, "target": target}],
    }


def production_for_shifts(session: Session, shifts: list[Shift]) -> dict[str, list[dict]]:
    if not shifts:
        return {"hourly": [], "daily": [], "shiftly": []}
    if len(shifts) == 1:
        one = _production_for_one_shift(session, shifts[0])
        for row in one["hourly"]:
            row.pop("hour", None)
        return one

    shiftly_acc: dict[str, dict] = {}
    daily_acc: dict[str, dict] = {}
    hourly_acc: dict = defaultdict(lambda: {"tonnage": 0.0, "target": 0.0, "target_seen": False})

    for shift in shifts:
        piece = _production_for_one_shift(session, shift)
        for row in piece["shiftly"]:
            name = row["label"]
            acc = shiftly_acc.setdefault(
                name,
                {"label": name, "tonnage": 0.0, "target": 0.0, "target_seen": False, "targetCycleMin": None},
            )
            acc["tonnage"] += row["tonnage"]
            if row.get("target") is not None:
                acc["target"] += row["target"]
                acc["target_seen"] = True
            if acc["targetCycleMin"] is None and row.get("targetCycleMin") is not None:
                acc["targetCycleMin"] = row["targetCycleMin"]
        for row in piece["daily"]:
            label = row["label"]
            acc = daily_acc.setdefault(label, {"label": label, "tonnage": 0.0, "target": 0.0, "target_seen": False})
            acc["tonnage"] += row["tonnage"]
            if row.get("target") is not None:
                acc["target"] += row["target"]
                acc["target_seen"] = True
        for row in piece["hourly"]:
            hour = row.get("hour")
            acc = hourly_acc[hour]
            acc["tonnage"] += row["tonnage"]
            if row.get("target") is not None:
                acc["target"] += row["target"]
                acc["target_seen"] = True

    multi_day = len({row["label"] for row in daily_acc.values()}) > 1
    hourly = []
    for hour in sorted((h for h in hourly_acc if h is not None)):
        acc = hourly_acc[hour]
        label = hour.strftime("%d/%m %Hh") if multi_day else hour.strftime("%Hh")
        hourly.append(
            {
                "label": label,
                "tonnage": acc["tonnage"],
                "target": acc["target"] if acc["target_seen"] else None,
            }
        )

    shiftly = []
    for name in ("Poste matin", "Poste après-midi", "Poste nuit"):
        acc = shiftly_acc.get(name)
        if not acc:
            continue
        target = acc["target"] if acc["target_seen"] else None
        entry = {"label": name, "tonnage": acc["tonnage"], "target": target}
        if acc["targetCycleMin"] is not None:
            entry["targetCycleMin"] = acc["targetCycleMin"]
        entry.update(shiftly_attainment(acc["tonnage"], target))
        shiftly.append(entry)
    for name, acc in shiftly_acc.items():
        if name in ("Poste matin", "Poste après-midi", "Poste nuit"):
            continue
        target = acc["target"] if acc["target_seen"] else None
        entry = {"label": name, "tonnage": acc["tonnage"], "target": target}
        entry.update(shiftly_attainment(acc["tonnage"], target))
        shiftly.append(entry)

    daily = []
    for label in sorted(daily_acc):
        acc = daily_acc[label]
        daily.append(
            {
                "label": label,
                "tonnage": acc["tonnage"],
                "target": acc["target"] if acc["target_seen"] else None,
            }
        )

    return {"shiftly": shiftly, "hourly": hourly, "daily": daily}


def production_summary(session: Session, ctx: OperationalContext) -> dict[str, list[dict]]:
    if not ctx.shift:
        return {"hourly": [], "daily": [], "shiftly": []}
    return production_for_shifts(session, [ctx.shift])
