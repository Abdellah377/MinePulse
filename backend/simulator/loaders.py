"""Excavator / loader runtime state for the simulation world."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from simulator.cycle_dynamics import CycleDynamicsConfig, sample_service_seconds


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
    baseline_service_factor: float = 1.0
    operating_rate_factor: float = 1.0
    active_truck_code: str | None = None
    waiting_queue: list[str] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)

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

    def enqueue(self, truck_code: str) -> None:
        if truck_code == self.active_truck_code or truck_code in self.waiting_queue:
            return
        self.waiting_queue.append(truck_code)

    def request_service(self, truck_code: str) -> bool:
        """FIFO service: one active truck per physical loader."""

        self.enqueue(truck_code)
        if self.active_truck_code is None and self.effective_capacity() > 0 and self.waiting_queue:
            self.active_truck_code = self.waiting_queue.pop(0)
        return self.active_truck_code == truck_code and self.effective_capacity() > 0

    def release_service(self, truck_code: str, *, requeue: bool = False) -> None:
        if self.active_truck_code == truck_code:
            self.active_truck_code = None
        if truck_code in self.waiting_queue:
            self.waiting_queue.remove(truck_code)
        if requeue:
            self.waiting_queue.insert(0, truck_code)

    def loading_rate(self) -> float:
        rate = self.effective_capacity() * max(0.35, min(1.08, self.operating_rate_factor))
        if self.slow_loading:
            rate *= 0.72
        return max(0.0, rate)

    def sample_loading_seconds(self, cfg: CycleDynamicsConfig) -> float:
        return sample_service_seconds(
            self.rng,
            cfg.loading_min_seconds,
            cfg.loading_max_seconds,
            self.baseline_service_factor,
        )
