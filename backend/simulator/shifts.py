"""Idempotent simulator shift schedule derived from operational time."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProductionTarget, Shift


def _shift_spec(sim_now: datetime) -> tuple[date, str, time, time]:
    current = sim_now.timetz().replace(tzinfo=None)
    if time(6, 0) <= current < time(14, 0):
        return sim_now.date(), "Poste matin", time(6, 0), time(14, 0)
    if time(14, 0) <= current < time(22, 0):
        return sim_now.date(), "Poste après-midi", time(14, 0), time(22, 0)
    if current >= time(22, 0):
        return sim_now.date(), "Poste nuit", time(22, 0), time(6, 0)
    return sim_now.date() - timedelta(days=1), "Poste nuit", time(22, 0), time(6, 0)


def ensure_simulation_shift(
    session: Session,
    *,
    site_id: int,
    material_id: int | None,
    sim_now: datetime,
) -> Shift:
    shift_date, name, start, end = _shift_spec(sim_now)
    shift = session.scalar(
        select(Shift).where(
            Shift.site_id == site_id,
            Shift.shift_date == shift_date,
            Shift.name == name,
        )
    )
    if shift is None:
        shift = Shift(
            site_id=site_id,
            shift_date=shift_date,
            name=name,
            start_time=start,
            end_time=end,
            status="ACTIVE",
        )
        session.add(shift)
        session.flush()
    target = session.scalar(
        select(ProductionTarget).where(ProductionTarget.shift_id == shift.shift_id)
    )
    if target is None:
        session.add(
            ProductionTarget(
                shift_id=shift.shift_id,
                material_id=material_id,
                target_tonnes=Decimal("42000"),
                target_cycles=240,
                target_utilization=Decimal("85"),
                target_cycle_min=Decimal("42"),
            )
        )
    return shift

