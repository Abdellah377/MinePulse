"""Canonical site/shift/current-time resolution for operational queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Shift, Site
from app.services.operational.clock import get_operational_now
from app.services.operational.ids import format_shift_id


@dataclass(frozen=True)
class OperationalContext:
    site: Site
    shift: Shift | None
    sim_now: datetime
    shift_window_start: datetime
    shift_window_end: datetime

    @property
    def site_code(self) -> str:
        return self.site.code

    @property
    def site_id(self) -> int:
        return self.site.site_id

    @property
    def shift_id(self) -> int | None:
        return self.shift.shift_id if self.shift else None

    @property
    def shift_dto_id(self) -> str | None:
        return format_shift_id(self.shift.shift_id) if self.shift else None


def sim_now_utc() -> datetime:
    return get_operational_now()


def _combine_shift_datetime(shift_date: date, t: time, tz: timezone = timezone.utc) -> datetime:
    return datetime.combine(shift_date, t, tzinfo=tz)


def shift_window(shift: Shift, sim_now: datetime) -> tuple[datetime, datetime]:
    """Return [start, end) for a shift entity, handling overnight shifts."""
    tz = sim_now.tzinfo or timezone.utc
    start = _combine_shift_datetime(shift.shift_date, shift.start_time, tz)
    end = _combine_shift_datetime(shift.shift_date, shift.end_time, tz)
    if end <= start:
        end = end + timedelta(days=1)
    # If sim is before today's shift start but after midnight, overnight shift may belong to prior calendar day
    if sim_now < start and shift.end_time < shift.start_time:
        start = start - timedelta(days=1)
        end = end - timedelta(days=1)
    return start, end


def resolve_site(session: Session, site_code: str | None) -> Site:
    if site_code:
        site = session.scalar(select(Site).where(Site.code == site_code, Site.active.is_(True)))
        if site:
            return site
        raise HTTPException(status_code=404, detail=f"Site not found: {site_code}")
    site = session.scalar(select(Site).where(Site.active.is_(True)).order_by(Site.site_id))
    if not site:
        raise HTTPException(status_code=404, detail="No active site")
    return site


def resolve_shift(
    session: Session,
    site_id: int,
    shift_id: int | None,
    sim_now: datetime,
) -> Shift | None:
    if shift_id is not None:
        shift = session.scalar(
            select(Shift).where(Shift.shift_id == shift_id, Shift.site_id == site_id)
        )
        if shift:
            return shift
        raise HTTPException(status_code=404, detail=f"Shift not found: {shift_id}")

    # Active shift: sim_now falls within shift window
    shifts = session.scalars(
        select(Shift).where(Shift.site_id == site_id).order_by(Shift.shift_date.desc(), Shift.start_time)
    ).all()
    for shift in shifts:
        start, end = shift_window(shift, sim_now)
        if start <= sim_now < end:
            return shift
    # Fallback: latest shift for site
    return session.scalar(
        select(Shift).where(Shift.site_id == site_id).order_by(Shift.shift_id.desc())
    )


def get_operational_context(
    session: Session,
    *,
    site_code: str | None = None,
    shift_id: int | None = None,
) -> OperationalContext:
    sim_now = sim_now_utc()
    site = resolve_site(session, site_code)
    shift = resolve_shift(session, site.site_id, shift_id, sim_now)
    if shift:
        start, end = shift_window(shift, sim_now)
    else:
        start = sim_now
        end = sim_now
    return OperationalContext(
        site=site,
        shift=shift,
        sim_now=sim_now,
        shift_window_start=start,
        shift_window_end=end,
    )
