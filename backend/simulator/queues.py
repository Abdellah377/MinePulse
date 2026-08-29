"""Zone capacity and waiting queues."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ZoneRuntime:
    code: str
    zone_id: int
    name: str
    zone_type: str
    base_capacity: int
    capacity: int
    closed: bool = False
    arrival_pressure: float = 1.0
    queue: list[str] = field(default_factory=list)
    occupants: list[str] = field(default_factory=list)

    def can_enter(self) -> bool:
        if self.closed:
            return False
        return len(self.occupants) < max(0, self.capacity)

    def enqueue(self, code: str) -> None:
        if code not in self.queue and code not in self.occupants:
            self.queue.append(code)

    def dequeue_next(self) -> str | None:
        if not self.queue or not self.can_enter():
            return None
        code = self.queue.pop(0)
        self.occupants.append(code)
        return code

    def enter(self, code: str) -> bool:
        if code in self.occupants:
            return True
        if not self.can_enter():
            self.enqueue(code)
            return False
        if code in self.queue:
            self.queue.remove(code)
        self.occupants.append(code)
        return True

    def leave(self, code: str) -> None:
        if code in self.occupants:
            self.occupants.remove(code)
        if code in self.queue:
            self.queue.remove(code)
        self.dequeue_next()


@dataclass
class RoadRuntime:
    code: str
    road_id: int
    from_zone: str
    to_zone: str
    distance_km: float
    base_speed_limit: float
    speed_limit: float
    grade_pct: float = 0.0
    quality_score: float = 85.0
    closed: bool = False
    slow_traffic_factor: float = 1.0
    operating_factor: float = 1.0
