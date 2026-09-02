"""Operational context and shift window tests."""

from datetime import date, datetime, time, timezone

from app.db.models import Shift
from app.services.operational.context import shift_window, resolve_shift
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


def test_resolve_shift_ignores_stale_explicit_shift_outside_sim_now():
    site_id = 1
    sim_now = datetime(2026, 1, 29, 10, 2, tzinfo=timezone.utc)
    covering = Shift(
        shift_id=1,
        site_id=site_id,
        name="Poste matin",
        shift_date=date(2026, 1, 29),
        start_time=time(6, 0),
        end_time=time(14, 0),
    )
    stale = Shift(
        shift_id=8,
        site_id=site_id,
        name="Poste après-midi",
        shift_date=date(2026, 1, 31),
        start_time=time(14, 0),
        end_time=time(22, 0),
    )

    class _Session:
        def scalars(self, _query):
            class Rows:
                def all(self_inner):
                    return [stale, covering]

            return Rows()

        def scalar(self, _query):
            return stale

    resolved = resolve_shift(_Session(), site_id, 8, sim_now)
    assert resolved is covering
    assert resolved.shift_id == 1

