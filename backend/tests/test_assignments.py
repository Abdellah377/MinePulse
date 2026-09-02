from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.models import Site
from app.services.operational.assignments import assignment_covers_sim_now, select_current_assignment
from app.services.operational.context import OperationalContext


def _ctx(sim_now: datetime, shift_id: int | None = 6) -> OperationalContext:
    site = Site(site_id=1, code="MP-SIM-01", name="Site", active=True)
    shift = None
    if shift_id is not None:
        shift = SimpleNamespace(shift_id=shift_id)
    return OperationalContext(
        site=site,
        shift=shift,  # type: ignore[arg-type]
        sim_now=sim_now,
        shift_window_start=sim_now,
        shift_window_end=sim_now,
    )


def _row(**overrides):
    values = dict(
        assignment_id=1,
        truck_id=2,
        loader_id=22,
        shift_id=4,
        origin_zone_id=2,
        destination_zone_id=5,
        status="ACTIVE",
        assigned_at=datetime(2026, 1, 30, 6, 0, tzinfo=timezone.utc),
        completed_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_assignment_covers_sim_now_keeps_later_completed_row():
    sim_now = datetime(2026, 1, 30, 6, 9, tzinfo=timezone.utc)
    covering = _row(
        status="COMPLETED",
        completed_at=datetime(2026, 1, 30, 14, 1, tzinfo=timezone.utc),
    )
    future = _row(
        assignment_id=2,
        shift_id=6,
        assigned_at=datetime(2026, 1, 30, 22, 0, tzinfo=timezone.utc),
        completed_at=None,
    )
    assert assignment_covers_sim_now(covering, sim_now) is True
    assert assignment_covers_sim_now(future, sim_now) is False


def test_select_current_assignment_falls_back_when_shift_disagrees():
    sim_now = datetime(2026, 1, 30, 6, 9, tzinfo=timezone.utc)
    covering = _row(
        assignment_id=4862,
        shift_id=4,
        status="COMPLETED",
        completed_at=datetime(2026, 1, 30, 14, 1, tzinfo=timezone.utc),
    )
    chosen = select_current_assignment([covering], _ctx(sim_now, shift_id=6))
    assert chosen is covering
    assert chosen.destination_zone_id == 5


def test_select_current_assignment_prefers_matching_shift():
    sim_now = datetime(2026, 1, 31, 7, 52, tzinfo=timezone.utc)
    previous = _row(
        assignment_id=4902,
        shift_id=6,
        status="COMPLETED",
        assigned_at=datetime(2026, 1, 30, 22, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 31, 6, 2, tzinfo=timezone.utc),
    )
    current = _row(
        assignment_id=4922,
        shift_id=7,
        assigned_at=datetime(2026, 1, 31, 6, 2, tzinfo=timezone.utc),
        completed_at=None,
    )
    chosen = select_current_assignment([previous, current], _ctx(sim_now, shift_id=7))
    assert chosen is current
