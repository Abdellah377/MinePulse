"""Cycle sample helpers — shift-scoped, no unscoped fallback."""

from app.services.operational.cycles import cycle_minutes_bucket


def test_cycle_minutes_bucket():
    assert cycle_minutes_bucket(12) == "<30"
    assert cycle_minutes_bucket(35) == "30-40"
    assert cycle_minutes_bucket(44) == "40-50"
    assert cycle_minutes_bucket(51) == "50+"
