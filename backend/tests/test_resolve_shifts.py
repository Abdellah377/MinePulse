"""resolve_shifts overlap including overnight nuit."""

from datetime import date, datetime, time, timezone

from app.db.models import Shift
from app.services.operational.context import (
    MAX_ANALYSIS_RANGE,
    analysis_window,
    period_span,
    shift_operational_span,
    shift_overlaps_period,
)


def _shift(name: str, day: date, start: time, end: time, shift_id: int = 1) -> Shift:
    return Shift(
        shift_id=shift_id,
        site_id=1,
        name=name,
        shift_date=day,
        start_time=start,
        end_time=end,
    )


def test_nuit_operational_span_crosses_midnight():
    shift = _shift("Poste nuit", date(2026, 1, 28), time(22, 0), time(6, 0))
    start, end = shift_operational_span(shift)
    assert start == datetime(2026, 1, 28, 22, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 29, 6, 0, tzinfo=timezone.utc)


def test_a_30_jan_matin_window_does_not_include_afternoon():
    matin_30 = _shift("Poste matin", date(2026, 1, 30), time(6, 0), time(14, 0), 1)
    apm_30 = _shift("Poste après-midi", date(2026, 1, 30), time(14, 0), time(22, 0), 2)
    period = (date(2026, 1, 30), date(2026, 1, 30))
    assert shift_overlaps_period(matin_30, *period)
    assert shift_overlaps_period(apm_30, *period)
    assert matin_30.name == "Poste matin"
    assert apm_30.name != "Poste matin"


def test_b_28_30_jan_nuit_includes_overnight_into_the_28th():
    nuit_27 = _shift("Poste nuit", date(2026, 1, 27), time(22, 0), time(6, 0), 1)
    nuit_28 = _shift("Poste nuit", date(2026, 1, 28), time(22, 0), time(6, 0), 2)
    nuit_30 = _shift("Poste nuit", date(2026, 1, 30), time(22, 0), time(6, 0), 3)
    period = (date(2026, 1, 28), date(2026, 1, 30))
    assert shift_overlaps_period(nuit_27, *period)
    assert shift_overlaps_period(nuit_28, *period)
    assert shift_overlaps_period(nuit_30, *period)


def test_period_span_is_half_open_next_midnight():
    start, end = period_span(date(2026, 1, 28), date(2026, 1, 30))
    assert start == datetime(2026, 1, 28, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 31, 0, 0, tzinfo=timezone.utc)


class _Ctx:
    site_id = 1
    sim_now = datetime(2026, 1, 30, 18, 0, tzinfo=timezone.utc)
    shift_window_start = datetime(2026, 1, 30, 14, 0, tzinfo=timezone.utc)
    shift_window_end = datetime(2026, 1, 30, 22, 0, tzinfo=timezone.utc)


def test_analysis_window_clips_to_seven_days(monkeypatch):
    from app.services.operational import context as ctx_mod

    early = _shift("Poste matin", date(2026, 1, 20), time(6, 0), time(14, 0), 1)
    late = _shift("Poste matin", date(2026, 1, 30), time(6, 0), time(14, 0), 2)
    monkeypatch.setattr(ctx_mod, "resolve_shifts", lambda *args, **kwargs: [early, late])
    since, until = analysis_window(None, _Ctx(), date(2026, 1, 20), date(2026, 1, 30), "matin")
    assert until == datetime(2026, 1, 30, 14, 0, tzinfo=timezone.utc)
    assert until - since == MAX_ANALYSIS_RANGE
