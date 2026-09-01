"""In-memory simulation world (truck fleet) + control path re-exports."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from simulator.config import SimConfig
from simulator.control import SIM_STATE_PATH, read_control, write_control  # noqa: F401
from simulator.state_machine import TruckPhase, TruckRuntime

# Re-export for backward compatibility
from simulator.control import read_control as _rc


def stable_seed(base: int, equipment_id: int, code: str) -> int:
    import hashlib

    digest = hashlib.sha256(f"{base}:{equipment_id}:{code}".encode()).hexdigest()
    return (base ^ equipment_id ^ int(digest[:8], 16)) & 0x7FFFFFFF


class SimWorld:
    def __init__(self, cfg: SimConfig) -> None:
        self.cfg = cfg
        self.trucks: dict[str, TruckRuntime] = {}
        self.excavators_down: set[str] = set()
        self.scenario_active: dict[str, dict] = {}
        self.scenario_events_fired: set[str] = set()

    def load_trucks(
        self,
        equip_rows: list[tuple[int, str]],
        seed: int,
        zone_centroids: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        centroids = zone_centroids or {}
        for eid, code in equip_rows:
            rng = random.Random(stable_seed(seed, eid, code))
            n = int(code.split("-")[1])
            loader = ("EXC-001", "EXC-002", "EXC-003")[(n - 1) % 3]
            bench = "BANC_B" if loader == "EXC-002" else "BANC_A"
            dest = "DUMP_N" if bench == "BANC_A" else "DUMP_S"
            if n % 3 == 0:
                dest = "CRUSHER"
            # A fresh cycle begins with the empty return leg at the dump point.
            lng, lat = centroids.get(dest, centroids.get(bench, (-6.682, 32.668)))
            self.trucks[code] = TruckRuntime(
                code=code,
                equipment_id=eid,
                origin_zone_code=bench,
                dest_zone_code=dest,
                haul_dest_zone_code=dest,
                loader_code=loader,
                phase=TruckPhase.MOVING_EMPTY,
                fuel_pct=rng.uniform(40, 95),
                odometer_km=rng.uniform(18000, 92000),
                engine_hours=rng.uniform(3500, 24000),
                lng=lng,
                lat=lat,
                baseline_travel_factor=rng.uniform(
                    self.cfg.cycle_dynamics.truck_factor_min,
                    self.cfg.cycle_dynamics.truck_factor_max,
                ),
                rng=rng,
            )

    def clear_scenario_memory(self) -> None:
        self.excavators_down.clear()
        self.scenario_active.clear()
        self.scenario_events_fired.clear()

    @staticmethod
    def read_control() -> dict:
        return read_control()

    @staticmethod
    def write_control(data: dict) -> None:
        write_control(data)
