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

POSTE_ID_TO_NAME = {
    "matin": "Poste matin",
    "apres-midi": "Poste après-midi",
    "nuit": "Poste nuit",
}

MAX_ANALYSIS_RANGE = timedelta(days=7)


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


def shift_operational_span(shift: Shift, tz: timezone = timezone.utc) -> tuple[datetime, datetime]:
    """Stored operational window [start, end) from shift_date + hours. Overnight adds one day."""
    start = _combine_shift_datetime(shift.shift_date, shift.start_time, tz)
    end = _combine_shift_datetime(shift.shift_date, shift.end_time, tz)
    if end <= start:
        end = end + timedelta(days=1)
    return start, end


def shift_window(shift: Shift, sim_now: datetime) -> tuple[datetime, datetime]:
    """Return [start, end) for a shift entity, handling overnight shifts."""
    tz = sim_now.tzinfo or timezone.utc
    start, end = shift_operational_span(shift, tz if isinstance(tz, timezone) else timezone.utc)
    # If sim is before today's shift start but after midnight, overnight shift may belong to prior calendar day
    if sim_now < start and shift.end_time < shift.start_time:
        start = start - timedelta(days=1)
        end = end - timedelta(days=1)
    return start, end


def period_span(from_date: date, to_date: date, tz: timezone = timezone.utc) -> tuple[datetime, datetime]:
    """Inclusive operational dates as [from 00:00, to+1 00:00)."""
    if to_date < from_date:
        from_date, to_date = to_date, from_date
    start = datetime.combine(from_date, time.min, tzinfo=tz)
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


def shift_overlaps_period(shift: Shift, from_date: date, to_date: date, tz: timezone = timezone.utc) -> bool:
    start, end = shift_operational_span(shift, tz)
    period_start, period_end = period_span(from_date, to_date, tz)
    return start < period_end and end > period_start


def parse_poste_name(poste: str | None) -> str | None:
    if not poste:
        return None
    name = POSTE_ID_TO_NAME.get(poste)
    if name is None:
        raise HTTPException(status_code=422, detail=f"Invalid poste: {poste}")
    return name


def resolve_shifts(
    session: Session,
    site_id: int,
    from_date: date,
    to_date: date,
    poste_name: str | None = None,
    tz: timezone = timezone.utc,
) -> list[Shift]:
    """Shift rows whose operational window overlaps [from 00:00, to+1 00:00), optional exact name."""
    if to_date < from_date:
        from_date, to_date = to_date, from_date
    q = (
        select(Shift)
        .where(
            Shift.site_id == site_id,
            Shift.shift_date >= from_date - timedelta(days=1),
            Shift.shift_date <= to_date,
        )
        .order_by(Shift.shift_date, Shift.start_time, Shift.shift_id)
    )
    if poste_name:
        q = q.where(Shift.name == poste_name)
    rows = list(session.scalars(q).all())
    return [shift for shift in rows if shift_overlaps_period(shift, from_date, to_date, tz)]


def analysis_window(
    session: Session,
    ctx: OperationalContext,
    from_date: date | None,
    to_date: date | None,
    poste: str | None,
) -> tuple[datetime, datetime]:
    """Union of resolved shift windows, clipped to sim_now and a 7-day cap."""
    if from_date is None and to_date is None and not poste:
        until = min(ctx.sim_now, ctx.shift_window_end)
        return ctx.shift_window_start, until

    from_date = from_date or ctx.sim_now.date()
    to_date = to_date or from_date
    poste_name = parse_poste_name(poste)
    tz = timezone.utc
    shifts = resolve_shifts(session, ctx.site_id, from_date, to_date, poste_name, tz)
    if not shifts:
        start, _ = period_span(from_date, to_date, tz)
        return start, start

    windows = [shift_operational_span(shift, tz) for shift in shifts]
    since = min(w[0] for w in windows)
    until = min(ctx.sim_now, max(w[1] for w in windows))
    if until - since > MAX_ANALYSIS_RANGE:
        since = until - MAX_ANALYSIS_RANGE
    if until < since:
        until = since
    return since, until


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


def _shift_covers(shift: Shift, sim_now: datetime) -> bool:
    start, end = shift_window(shift, sim_now)
    return start <= sim_now < end


def resolve_shift(
    session: Session,
    site_id: int,
    shift_id: int | None,
    sim_now: datetime,
) -> Shift | None:
    shifts = list(
        session.scalars(
            select(Shift).where(Shift.site_id == site_id).order_by(Shift.shift_date.desc(), Shift.start_time)
        ).all()
    )
    covering = next((row for row in shifts if _shift_covers(row, sim_now)), None)
    if shift_id is not None:
        requested = next((row for row in shifts if row.shift_id == shift_id), None)
        if requested is None:
            raise HTTPException(status_code=404, detail=f"Shift not found: {shift_id}")
        # After a clock reset the UI may still send a future/past poste.
        # Live operational reads (assignments, optimizer) must use the shift
        # that actually contains sim_now — otherwise destination is dropped.
        if covering is not None and requested.shift_id != covering.shift_id:
            return covering
        return requested
    if covering is not None:
        return covering
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
