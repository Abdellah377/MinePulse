"""Operational context and shift window tests."""

from datetime import date, datetime, time, timezone

from app.db.models import Shift
from app.services.operational.context import shift_window
from app.services.operational.ids import format_shift_id, parse_shift_id


def test_shift_window_day_shift():
    shift = Shift(
        shift_id=1,
        site_id=1,
        name="Matin",
        shift_date=date(2026, 1, 29),
        start_time=time(6, 0),
        end_time=time(14, 0),
    )
    sim_now = datetime(2026, 1, 29, 10, 30, tzinfo=timezone.utc)
    start, end = shift_window(shift, sim_now)
    assert start.hour == 6
    assert end.hour == 14
    assert start <= sim_now < end


def test_format_parse_shift_id_roundtrip():
    assert parse_shift_id(format_shift_id(12)) == 12
