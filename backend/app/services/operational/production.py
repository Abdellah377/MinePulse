"""Production targets and actuals summary."""

from __future__ import annotations

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


def production_summary(session: Session, ctx: OperationalContext) -> dict[str, list[dict]]:
    shift_id = ctx.shift_id
    if not shift_id or not ctx.shift:
        return {"hourly": [], "daily": [], "shiftly": []}

    shift = ctx.shift
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
        label = hour.strftime("%Hh") if hour else "?"
        hourly.append(
            {
                "label": label,
                "tonnage": t,
                "target": hourly_target,
            }
        )

    shift_label = shift.name
    daily_label = shift.shift_date.isoformat()

    target_cycle_min: float | None = None
    if target_row and target_row.metadata_:
        raw = target_row.metadata_.get("target_cycle_min")
        if raw is not None:
            try:
                target_cycle_min = float(raw)
            except (TypeError, ValueError):
                pass

    shiftly_entry: dict = {
        "label": shift_label,
        "tonnage": total,
        "target": target,
    }
    if target_cycle_min is not None:
        shiftly_entry["targetCycleMin"] = target_cycle_min

    shiftly_entry.update(shiftly_attainment(total, target))

    return {
        "shiftly": [shiftly_entry],
        "hourly": hourly,
        "daily": [{"label": daily_label, "tonnage": total, "target": target}],
    }
