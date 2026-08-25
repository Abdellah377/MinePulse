"""Excavator / loader runtime state for the simulation world."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoaderRuntime:
    code: str
    equipment_id: int
    zone_code: str = "BANC_A"
    available: bool = True
    capacity_factor: float = 1.0  # 1.0 = full, 0.5 = reduced, 0.0 = broken
    mechanical_breakdown: bool = False
    communication_lost: bool = False
    slow_loading: bool = False
    in_maintenance: bool = False

    def effective_capacity(self) -> float:
        if self.mechanical_breakdown or not self.available:
            return 0.0
        return max(0.0, min(1.0, self.capacity_factor))

    def loading_time_multiplier(self) -> float:
        """Higher = slower loading. Infinite wait if capacity 0."""
        c = self.effective_capacity()
        if c <= 0:
            return 999.0
        base = 1.0 / c
        if self.slow_loading:
            return base * 2.0
        return base
