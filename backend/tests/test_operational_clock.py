import inspect
from datetime import date, datetime, time, timezone

from app.db.models import Shift, Site
from app.services.operational.clock import RealUtcClock
from app.services.operational import context
from app.services.simulator_clock import SimulationClock


def test_simulation_clock_returns_simulated_time(monkeypatch):
    expected = datetime(2026, 8, 21, 9, 15, tzinfo=timezone.utc)

    from simulator.world import SimWorld

    monkeypatch.setattr(SimWorld, "read_control", staticmethod(lambda: {"sim_now": expected.isoformat()}))

    assert SimulationClock().now() == expected


def test_real_clock_returns_timezone_aware_utc():
    now = RealUtcClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(now)


def test_context_resolver_uses_clock_abstraction_without_simulator(monkeypatch):
    now = datetime(2026, 8, 21, 7, 0, tzinfo=timezone.utc)
    site = Site(site_id=7, code="SITE-B", name="Site B", active=True)
    shift = Shift(
        shift_id=9,
        site_id=7,
        name="Matin",
        shift_date=date(2026, 8, 21),
        start_time=time(6, 0),
        end_time=time(14, 0),
    )

    monkeypatch.setattr(context, "get_operational_now", lambda: now)
    monkeypatch.setattr(context, "resolve_site", lambda session, site_code: site)
    monkeypatch.setattr(context, "resolve_shift", lambda session, site_id, shift_id, sim_now: shift)

    resolved = context.get_operational_context(object(), site_code="SITE-B")

    assert resolved.sim_now == now
    assert resolved.site_id == 7
    assert resolved.shift_id == 9
    assert "simulator" not in inspect.getsource(context)
