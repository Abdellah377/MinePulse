"""Operational current-time providers.

Core operational services depend on this module instead of importing the
simulator directly. Simulation remains the default provider to preserve the
current accelerated demo behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app.config import get_settings


class CurrentTimeProvider(Protocol):
    def now(self) -> datetime:
        """Return the authoritative operational timestamp."""


def _aware_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


class RealUtcClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def get_operational_clock(mode: str | None = None) -> CurrentTimeProvider:
    configured = mode or getattr(get_settings(), "operational_clock", "simulation")
    if configured.lower() in {"real", "utc", "production", "prod"}:
        return RealUtcClock()
    from app.services.simulator_clock import SimulationClock

    return SimulationClock()


def get_operational_now(provider: CurrentTimeProvider | None = None) -> datetime:
    clock = provider or get_operational_clock()
    return _aware_utc(clock.now())
