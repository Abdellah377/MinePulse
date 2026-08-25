"""Simulation/test sensor thresholds — not manufacturer OEM limits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimThreshold:
    """Prototype range used by MinePulse simulation only."""

    key: str
    warn_low: float | None = None
    warn_high: float | None = None
    crit_low: float | None = None
    crit_high: float | None = None
    unit: str = ""
    source: str = "simulation/test"


# Named explicitly as simulation/test — never present as CAT/Komatsu limits.
SIM_THRESHOLDS: dict[str, SimThreshold] = {
    "engine_temp_c": SimThreshold("engine_temp_c", warn_high=98.0, crit_high=105.0, unit="°C"),
    "coolant_temp_c": SimThreshold("coolant_temp_c", warn_high=95.0, crit_high=102.0, unit="°C"),
    "oil_pressure_kpa": SimThreshold("oil_pressure_kpa", warn_low=220.0, crit_low=160.0, unit="kPa"),
    "battery_voltage": SimThreshold("battery_voltage", warn_low=24.0, crit_low=22.5, unit="V"),
    "fuel_rate_lph": SimThreshold("fuel_rate_lph", warn_high=38.0, crit_high=48.0, unit="l/h"),
    "communication_quality": SimThreshold("communication_quality", warn_low=60.0, crit_low=30.0, unit="%"),
    "tyre_pressure_kpa": SimThreshold("tyre_pressure_kpa", warn_low=520.0, crit_low=430.0, warn_high=850.0, unit="kPa"),
    "tyre_temp_c": SimThreshold("tyre_temp_c", warn_high=75.0, crit_high=90.0, unit="°C"),
}


def classify_value(key: str, value: float) -> str | None:
    """Return 'critical' | 'warning' | None (in range)."""
    t = SIM_THRESHOLDS.get(key)
    if t is None:
        return None
    if t.crit_low is not None and value <= t.crit_low:
        return "critical"
    if t.crit_high is not None and value >= t.crit_high:
        return "critical"
    if t.warn_low is not None and value <= t.warn_low:
        return "warning"
    if t.warn_high is not None and value >= t.warn_high:
        return "warning"
    return None


def expected_range(key: str) -> tuple[float | None, float | None]:
    t = SIM_THRESHOLDS.get(key)
    if t is None:
        return None, None
    lo = t.crit_low if t.crit_low is not None else t.warn_low
    hi = t.crit_high if t.crit_high is not None else t.warn_high
    return lo, hi
