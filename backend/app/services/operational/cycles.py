"""Shift-scoped cycle/trip metrics."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.db.models import Cycle, Equipment
from app.mappers.enums import EQUIPMENT_TYPE_TO_UI
from app.services.operational.context import OperationalContext


def apply_completed_cycle_shift_filter(q: Select, ctx: OperationalContext) -> Select:
    """Restrict completed cycles to the active OperationalContext shift window."""
    if ctx.shift_id is not None:
        return q.where(
            or_(
                Cycle.shift_id == ctx.shift_id,
                (
                    Cycle.shift_id.is_(None)
                    & (Cycle.completed_at >= ctx.shift_window_start)
                    & (Cycle.completed_at < ctx.shift_window_end)
                ),
            )
        )
    return q.where(
        Cycle.completed_at >= ctx.shift_window_start,
        Cycle.completed_at < ctx.shift_window_end,
    )


def cycle_minutes_bucket(minutes: float) -> str:
    if minutes < 30:
        return "<30"
    if minutes < 40:
        return "30-40"
    if minutes < 50:
        return "40-50"
    return "50+"


def shift_trip_counts(session: Session, ctx: OperationalContext) -> dict[int, int]:
    """Completed cycles for the active shift only."""
    q = (
        select(Cycle.truck_id, func.count())
        .join(Equipment, Equipment.equipment_id == Cycle.truck_id)
        .where(
            Equipment.site_id == ctx.site_id,
            Cycle.status == "COMPLETED",
            Cycle.completed_at.is_not(None),
        )
    )
    q = apply_completed_cycle_shift_filter(q, ctx)
    rows = session.execute(q.group_by(Cycle.truck_id)).all()
    return {int(tid): int(c) for tid, c in rows}


def avg_cycle_minutes_bulk(
    session: Session,
    equipment_ids: list[int],
    ctx: OperationalContext,
) -> dict[int, float | None]:
    """One grouped query for shift-scoped average cycle duration per truck."""
    if not equipment_ids:
        return {}
    q = select(Cycle.truck_id, Cycle.total_duration_sec).where(
        Cycle.truck_id.in_(equipment_ids),
        Cycle.status == "COMPLETED",
        Cycle.total_duration_sec.is_not(None),
        Cycle.completed_at.is_not(None),
    )
    q = apply_completed_cycle_shift_filter(q, ctx)
    rows = session.execute(q).all()
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for truck_id, dur in rows:
        sums[truck_id] = sums.get(truck_id, 0.0) + float(dur or 0)
        counts[truck_id] = counts.get(truck_id, 0) + 1
    out: dict[int, float | None] = {eid: None for eid in equipment_ids}
    for eid, cnt in counts.items():
        if cnt:
            out[eid] = round(sums[eid] / cnt / 60.0, 1)
    return out


def avg_cycle_minutes_for_equipment(
    session: Session,
    equipment_id: int,
    ctx: OperationalContext,
) -> float | None:
    q = select(Cycle.total_duration_sec).where(
        Cycle.truck_id == equipment_id,
        Cycle.status == "COMPLETED",
        Cycle.total_duration_sec.is_not(None),
        Cycle.completed_at.is_not(None),
    )
    q = apply_completed_cycle_shift_filter(q, ctx)
    rows = session.scalars(q).all()
    if not rows:
        return None
    avg_sec = sum(int(s or 0) for s in rows) / len(rows)
    return round(avg_sec / 60.0, 1)


def cycle_time_samples(session: Session, ctx: OperationalContext, limit: int = 500) -> list[dict]:
    """Completed-cycle durations for the active shift only (not last-N unscoped)."""
    q = (
        select(Cycle.total_duration_sec, Equipment.type)
        .join(Equipment, Equipment.equipment_id == Cycle.truck_id)
        .where(
            Equipment.site_id == ctx.site_id,
            Cycle.status == "COMPLETED",
            Cycle.total_duration_sec.is_not(None),
            Cycle.completed_at.is_not(None),
        )
        .order_by(Cycle.completed_at.desc())
        .limit(limit)
    )
    q = apply_completed_cycle_shift_filter(q, ctx)
    rows = session.execute(q).all()
    samples = []
    for dur, etype in rows:
        minutes = (dur or 0) / 60.0
        samples.append(
            {
                "equipmentType": EQUIPMENT_TYPE_TO_UI.get(etype, "other"),
                "bucket": cycle_minutes_bucket(minutes),
                "minutes": round(minutes, 1),
            }
        )
    return samples
