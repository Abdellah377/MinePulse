"""Fleet bulk context: missing keys do not trigger per-truck queries."""

from datetime import datetime, timezone

from app.mappers.dto import _cycle_actuel
from app.services.operational.equipment import FleetBulkContext


def test_cycle_actuel_with_bulk_missing_key_is_empty():
    bulk = FleetBulkContext()
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    stages = _cycle_actuel(None, 99, bulk=bulk, sim_now=now)
    assert stages
    assert all(s["minutes"] is None for s in stages)
    assert all(s["isCurrent"] is False for s in stages)
