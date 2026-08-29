"""Rich simulation world: injections, loaders, zones, roads, event helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from simulator.commands import append_event_log
from simulator.control import RUNTIME_SNAPSHOT_PATH
from simulator.cycle_dynamics import operating_conditions
from simulator.loaders import LoaderRuntime
from simulator.queues import RoadRuntime, ZoneRuntime
from simulator.state_machine import TruckPhase, TruckRuntime
from simulator.world import SimWorld, stable_seed


@dataclass
class ActiveInjection:
    injection_id: str
    command_id: str
    target_type: str
    target_id: str
    action: str
    parameters: dict[str, Any]
    started_at: str
    expires_at: str | None  # None = until manual restore
    ground_truth: str
    original_state: dict[str, Any] = field(default_factory=dict)
    alert_type: str | None = None


class SimulationWorld(SimWorld):
    """Extends SimWorld with loaders, zone/road runtime, injections, ground truth."""

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self.loaders: dict[str, LoaderRuntime] = {}
        self.zones: dict[str, ZoneRuntime] = {}
        self.roads: dict[str, RoadRuntime] = {}
        self.injections: dict[str, ActiveInjection] = {}
        self.ground_truth: list[dict] = []
        self.mode: str = "MANUAL"
        self.wall_started_at: datetime | None = None
        self.wall_elapsed_sec: float = 0.0
        self._operating_period_token: int | None = None

    def clear_scenario_memory(self) -> None:
        super().clear_scenario_memory()
        self.injections.clear()
        self.ground_truth.clear()
        for ldr in self.loaders.values():
            ldr.available = True
            ldr.capacity_factor = 1.0
            ldr.mechanical_breakdown = False
            ldr.communication_lost = False
            ldr.active_truck_code = None
            ldr.waiting_queue.clear()
        for z in self.zones.values():
            z.capacity = z.base_capacity
            z.closed = False
            z.queue.clear()
            z.occupants.clear()
        for r in self.roads.values():
            r.closed = False
            r.speed_limit = r.base_speed_limit
            r.slow_traffic_factor = 1.0
            r.operating_factor = 1.0
        self._operating_period_token = None

    def add_injection(self, inj: ActiveInjection) -> None:
        self.injections[inj.injection_id] = inj
        self.ground_truth.append(
            {
                "injection_id": inj.injection_id,
                "at": inj.started_at,
                "truth": inj.ground_truth,
            }
        )

    def remove_injection(self, injection_id: str) -> ActiveInjection | None:
        return self.injections.pop(injection_id, None)

    def expire_due_injections(self, sim_now: datetime) -> list[ActiveInjection]:
        expired: list[ActiveInjection] = []
        for iid, inj in list(self.injections.items()):
            if inj.expires_at is None:
                continue
            exp = datetime.fromisoformat(inj.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if sim_now >= exp:
                expired.append(inj)
                del self.injections[iid]
        return expired

    def log_test(self, sim_now: datetime, message: str, target_type: str | None = None, target_id: str | None = None) -> None:
        append_event_log(sim_now=sim_now, kind="TEST", message=message, target_type=target_type, target_id=target_id)

    def log_sim(self, sim_now: datetime, message: str, target_type: str | None = None, target_id: str | None = None) -> None:
        append_event_log(sim_now=sim_now, kind="SIMULATION", message=message, target_type=target_type, target_id=target_id)

    def loader_for_truck(self, truck: TruckRuntime) -> LoaderRuntime | None:
        return self.loaders.get(truck.loader_code)

    def truck_may_load(self, truck: TruckRuntime) -> bool:
        zone = self.zones.get(truck.origin_zone_code)
        if zone and (zone.closed or truck.code not in zone.occupants):
            return False
        ldr = self.loader_for_truck(truck)
        if ldr is None:
            return False
        return ldr.request_service(truck.code)

    def refresh_operating_conditions(self, sim_now: datetime) -> None:
        """Refresh bounded hourly conditions without exposing their hidden values."""

        minutes = self.cfg.cycle_dynamics.operating_period_minutes
        token = int(sim_now.timestamp()) // (max(1, minutes) * 60)
        if token == self._operating_period_token:
            return
        self._operating_period_token = token
        for road in self.roads.values():
            conditions = operating_conditions(
                seed=self.cfg.random_seed,
                sim_now=sim_now,
                asset_token=f"road:{road.code}",
                period_minutes=minutes,
            )
            road.operating_factor = conditions.travel_factor
        for loader in self.loaders.values():
            conditions = operating_conditions(
                seed=self.cfg.random_seed,
                sim_now=sim_now,
                asset_token=f"loader:{loader.code}",
                period_minutes=minutes,
            )
            loader.operating_rate_factor = conditions.loader_rate_factor

    def effective_road(self, from_code: str, to_code: str) -> RoadRuntime | None:
        key = f"{from_code}->{to_code}"
        for r in self.roads.values():
            if f"{r.from_zone}->{r.to_zone}" == key or r.code == key:
                return r
            if r.from_zone == from_code and r.to_zone == to_code:
                return r
            if r.from_zone == to_code and r.to_zone == from_code:
                return r
        return None

    def write_runtime_snapshot(
        self,
        sim_now: datetime,
        status: str,
        speed: float,
        *,
        causal_scenarios: list[dict[str, Any]] | None = None,
    ) -> None:
        payload = {
            "sim_now": sim_now.isoformat(),
            "status": status,
            "speed": speed,
            "mode": self.mode,
            "injections": [asdict(i) for i in self.injections.values()],
            # Simulator/developer status only. Operational APIs and AI evidence
            # never read this runtime file.
            "causal_scenarios": causal_scenarios or [],
            "zones": {
                c: {
                    "capacity": z.capacity,
                    "base_capacity": z.base_capacity,
                    "closed": z.closed,
                    "queue": list(z.queue),
                    "occupants": list(z.occupants),
                    "name": z.name,
                    "type": z.zone_type,
                }
                for c, z in self.zones.items()
            },
            "roads": {
                c: {
                    "closed": r.closed,
                    "speed_limit": r.speed_limit,
                    "base_speed_limit": r.base_speed_limit,
                    "from_zone": r.from_zone,
                    "to_zone": r.to_zone,
                    "distance_km": r.distance_km,
                }
                for c, r in self.roads.items()
            },
            "loaders": {
                c: {
                    "available": l.available,
                    "capacity_factor": l.capacity_factor,
                    "mechanical_breakdown": l.mechanical_breakdown,
                    "zone_code": l.zone_code,
                }
                for c, l in self.loaders.items()
            },
            "trucks": {
                c: {
                    "phase": t.phase.value,
                    "speed_kmh": t.speed_kmh,
                    "payload_t": t.payload_t,
                    "fuel_pct": t.fuel_pct,
                    "comm_lost": t.comm_lost,
                    "zone": t.origin_zone_code if t.phase.value.startswith("WAITING") or t.phase == TruckPhase.LOADING else t.dest_zone_code,
                    "origin": t.origin_zone_code,
                    "dest": t.dest_zone_code,
                    "loader": t.loader_code,
                    "road": t.active_road_code,
                }
                for c, t in self.trucks.items()
            },
            "ground_truth_count": len(self.ground_truth),
        }
        RUNTIME_SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def read_runtime_snapshot() -> dict:
        if RUNTIME_SNAPSHOT_PATH.exists():
            return json.loads(RUNTIME_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return {}
