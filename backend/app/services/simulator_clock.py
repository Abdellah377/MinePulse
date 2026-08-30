"""Simulator-backed operational clock adapter."""

from __future__ import annotations

from datetime import datetime, timezone


def _aware_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def simulation_control() -> dict:
    from simulator.world import SimWorld
    from simulator.file_io import RuntimeFileError
    from app.services.operational.clock import OperationalClockUnavailable

    try:
        return SimWorld.read_control()
    except RuntimeFileError as exc:
        raise OperationalClockUnavailable("Operational simulation clock unavailable") from exc


class SimulationClock:
    def now(self) -> datetime:
        control = simulation_control()
        return _aware_utc(datetime.fromisoformat(control["sim_now"]))
