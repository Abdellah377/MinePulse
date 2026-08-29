"""Truck operational state machine."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum

from app.db.enums import EquipmentState
from simulator.cycle_dynamics import sample_service_seconds, sample_temporal_factor


class TruckPhase(str, Enum):
    WAITING_LOADING = "WAITING_LOADING"
    LOADING = "LOADING"
    MOVING_LOADED = "MOVING_LOADED"
    WAITING_DUMPING = "WAITING_DUMPING"
    DUMPING = "DUMPING"
    MOVING_EMPTY = "MOVING_EMPTY"
    REFUELING = "REFUELING"
    STOPPED = "STOPPED"
    NO_COMM = "NO_COMM"


PHASE_TO_DB: dict[TruckPhase, EquipmentState] = {
    TruckPhase.WAITING_LOADING: EquipmentState.WAITING_LOADING,
    TruckPhase.LOADING: EquipmentState.LOADING,
    TruckPhase.MOVING_LOADED: EquipmentState.MOVING_LOADED,
    TruckPhase.WAITING_DUMPING: EquipmentState.WAITING_DUMPING,
    TruckPhase.DUMPING: EquipmentState.DUMPING,
    TruckPhase.MOVING_EMPTY: EquipmentState.MOVING_EMPTY,
    TruckPhase.REFUELING: EquipmentState.REFUELING,
    TruckPhase.STOPPED: EquipmentState.STOPPED_UNDEFINED,
    TruckPhase.NO_COMM: EquipmentState.NO_DATA,
}

# Cycle stage sequence numbers
STAGE_SEQUENCE: dict[EquipmentState, int] = {
    EquipmentState.MOVING_EMPTY: 1,
    EquipmentState.WAITING_LOADING: 2,
    EquipmentState.LOADING: 3,
    EquipmentState.MOVING_LOADED: 4,
    EquipmentState.WAITING_DUMPING: 5,
    EquipmentState.DUMPING: 6,
}

CYCLE_PHASES = {
    TruckPhase.MOVING_EMPTY,
    TruckPhase.WAITING_LOADING,
    TruckPhase.LOADING,
    TruckPhase.MOVING_LOADED,
    TruckPhase.WAITING_DUMPING,
    TruckPhase.DUMPING,
}


@dataclass
class TruckRuntime:
    code: str
    equipment_id: int
    phase: TruckPhase = TruckPhase.WAITING_LOADING
    origin_zone_code: str = "BANC_A"
    dest_zone_code: str = "CRUSHER"
    haul_dest_zone_code: str = "CRUSHER"  # restored after refuel
    loader_code: str = "EXC-001"
    active_road_code: str | None = None
    road_reverse: bool = False
    road_distance_km: float = 4.0
    road_speed_limit: float = 40.0
    road_grade_pct: float = 0.0
    road_quality_score: float = 85.0
    road_progress: float = 0.0
    phase_ticks_left: int = 5
    phase_seconds_left: float = 0.0
    phase_seconds_total: float = 0.0
    phase_payload_start: float = 0.0
    phase_payload_target: float = 0.0
    next_loading_duration_seconds: float | None = None
    payload_t: float = 0.0
    fuel_pct: float = 85.0
    speed_kmh: float = 0.0
    heading_deg: float = 0.0
    odometer_km: float = 25000.0
    engine_hours: float = 8000.0
    lng: float = -6.682
    lat: float = 32.668
    comm_lost: bool = False
    gps_lost: bool = False
    unexplained_hold: bool = False
    mechanical_hold: bool = False
    engine_off: bool = False
    high_engine_temp: bool = False
    in_maintenance: bool = False
    low_oil_pressure: bool = False
    battery_low: bool = False
    fuel_rate_factor: float = 1.0
    sensor_signal_loss: bool = False
    comm_quality_drop: bool = False
    tyre_pressure_low: bool = False
    tyre_temp_high: bool = False
    tyre_fault_position: str | None = None
    engine_temp_c: float = 86.0
    coolant_temp_c: float = 80.0
    oil_pressure_kpa: float = 410.0
    battery_voltage: float = 27.2
    communication_quality: float = 95.0
    baseline_travel_factor: float = 1.0
    travel_condition_factor: float = 1.0
    # Optional causal-scenario targets. These are simulator runtime controls;
    # only their resulting telemetry/state is persisted.
    performance_factor: float = 1.0
    scenario_oil_pressure_target: float | None = None
    scenario_engine_temp_target: float | None = None
    scenario_coolant_temp_target: float | None = None
    scenario_comm_quality_target: float | None = None
    scenario_tyre_pressure_target: float | None = None
    scenario_tyre_temp_target: float | None = None
    tyres: dict = field(default_factory=dict)
    active_oem_codes: set = field(default_factory=set)
    pre_stop_phase: TruckPhase | None = None
    rng: random.Random = field(default_factory=random.Random)

    def db_state(self) -> EquipmentState:
        return PHASE_TO_DB[self.phase]

    def is_moving(self) -> bool:
        return self.phase in (TruckPhase.MOVING_LOADED, TruckPhase.MOVING_EMPTY, TruckPhase.REFUELING)

    def _engine_running(self) -> bool:
        return (
            not self.comm_lost
            and not self.engine_off
            and self.phase not in (TruckPhase.STOPPED, TruckPhase.NO_COMM)
        )

    @staticmethod
    def _sim_seconds(cfg) -> float:
        return max(0.1, float(cfg.tick_seconds) * float(cfg.speed))

    def hold_for_next_tick(self, cfg) -> None:
        self.phase_seconds_left = max(self.phase_seconds_left, self._sim_seconds(cfg))
        self.phase_seconds_total = max(self.phase_seconds_total, self.phase_seconds_left)
        self.phase_ticks_left = max(1, math.ceil(self.phase_seconds_left / self._sim_seconds(cfg)))
        self.speed_kmh = 0.0

    def reset_phase_timing(self) -> None:
        self.phase_ticks_left = 5
        self.phase_seconds_left = 0.0
        self.phase_seconds_total = 0.0
        self.next_loading_duration_seconds = None

    def _begin_timed_phase(self, cfg, phase: TruckPhase, duration_seconds: float) -> None:
        self.phase = phase
        self.phase_seconds_total = max(self._sim_seconds(cfg), float(duration_seconds))
        self.phase_seconds_left = self.phase_seconds_total
        self.phase_ticks_left = max(1, math.ceil(self.phase_seconds_left / self._sim_seconds(cfg)))
        self.speed_kmh = 0.0
        if phase == TruckPhase.LOADING:
            self.phase_payload_start = max(0.0, self.payload_t)
            self.phase_payload_target = cfg.default_truck_payload * self.rng.uniform(0.94, 1.03)
        elif phase == TruckPhase.DUMPING:
            self.phase_payload_start = max(0.0, self.payload_t)
            self.phase_payload_target = 0.0

    def _advance_timed_phase(self, cfg, *, loading_rate: float) -> bool:
        if self.phase not in {
            TruckPhase.WAITING_LOADING,
            TruckPhase.LOADING,
            TruckPhase.WAITING_DUMPING,
            TruckPhase.DUMPING,
        }:
            return True
        if self.phase_seconds_total <= 0:
            self.phase_seconds_total = max(
                self._sim_seconds(cfg), self.phase_ticks_left * self._sim_seconds(cfg)
            )
            self.phase_seconds_left = self.phase_seconds_total
            if self.phase == TruckPhase.LOADING:
                self.phase_payload_start = self.payload_t
                self.phase_payload_target = cfg.default_truck_payload
            elif self.phase == TruckPhase.DUMPING:
                self.phase_payload_start = self.payload_t
                self.phase_payload_target = 0.0

        rate = max(0.02, loading_rate) if self.phase == TruckPhase.LOADING else 1.0
        self.phase_seconds_left = max(0.0, self.phase_seconds_left - self._sim_seconds(cfg) * rate)
        self.phase_ticks_left = math.ceil(self.phase_seconds_left / self._sim_seconds(cfg))
        progress = 1.0 - self.phase_seconds_left / max(0.1, self.phase_seconds_total)
        if self.phase == TruckPhase.LOADING:
            self.payload_t = self.phase_payload_start + (
                self.phase_payload_target - self.phase_payload_start
            ) * progress
            self.fuel_pct = max(0.0, self.fuel_pct - 0.02)
        elif self.phase == TruckPhase.DUMPING:
            self.payload_t = max(0.0, self.phase_payload_start * (1.0 - progress))
        self.speed_kmh = 0.0
        return self.phase_seconds_left <= 0

    def advance_phase(
        self,
        cfg,
        *,
        loading_rate: float = 1.0,
        loading_duration_seconds: float | None = None,
    ) -> None:
        sim_hours = self._sim_seconds(cfg) / 3600.0
        if self._engine_running():
            self.engine_hours += sim_hours

        if self.comm_lost:
            self.phase = TruckPhase.NO_COMM
            self.speed_kmh = 0
            return

        if self.engine_off or self.in_maintenance:
            self.phase = TruckPhase.STOPPED
            self.speed_kmh = 0
            return

        if self.mechanical_hold or self.unexplained_hold:
            self.phase = TruckPhase.STOPPED
            self.speed_kmh = 0
            return

        if (
            self.fuel_pct < cfg.fuel_low_threshold
            and self.phase
            not in (
                TruckPhase.REFUELING,
                TruckPhase.LOADING,
                TruckPhase.DUMPING,
                TruckPhase.MOVING_EMPTY,
                TruckPhase.MOVING_LOADED,
            )
        ):
            self.haul_dest_zone_code = self.dest_zone_code
            self.phase = TruckPhase.REFUELING
            self.dest_zone_code = "FUEL"
            self.road_progress = 0.0
            self.phase_ticks_left = self.rng.randint(8, 15)
            self.phase_seconds_left = 0.0
            self.phase_seconds_total = 0.0
            return

        # Finish road before phase transition when moving
        if self.is_moving() and self.road_progress < 1.0:
            self._apply_motion(cfg)
            return

        if not self._advance_timed_phase(cfg, loading_rate=loading_rate):
            return

        if self.phase == TruckPhase.REFUELING:
            self.fuel_pct = min(100, self.fuel_pct + 15)
            if self.fuel_pct < 95:
                self.phase_ticks_left = 3
                self.speed_kmh = 0
                return
            # Restore haul destination after refuel
            self.dest_zone_code = self.haul_dest_zone_code

        prev = self.phase
        dynamics = getattr(cfg, "cycle_dynamics", None)
        if prev == TruckPhase.WAITING_LOADING:
            duration = loading_duration_seconds or self.next_loading_duration_seconds
            if duration is None:
                minimum = getattr(dynamics, "loading_min_seconds", cfg.loading_min_seconds)
                maximum = getattr(dynamics, "loading_max_seconds", cfg.loading_max_seconds)
                duration = self.rng.uniform(minimum, maximum)
            self.next_loading_duration_seconds = None
            self._begin_timed_phase(cfg, TruckPhase.LOADING, duration)
        elif prev == TruckPhase.LOADING:
            self.phase = TruckPhase.MOVING_LOADED
        elif prev == TruckPhase.MOVING_LOADED:
            minimum = getattr(dynamics, "waiting_dump_min_seconds", 25.0)
            maximum = getattr(dynamics, "waiting_dump_max_seconds", 150.0)
            self._begin_timed_phase(
                cfg, TruckPhase.WAITING_DUMPING, self.rng.uniform(minimum, maximum)
            )
        elif prev == TruckPhase.WAITING_DUMPING:
            minimum = getattr(dynamics, "dumping_min_seconds", cfg.dump_min_seconds)
            maximum = getattr(dynamics, "dumping_max_seconds", cfg.dump_max_seconds)
            duration = sample_service_seconds(self.rng, minimum, maximum, 1.0)
            self._begin_timed_phase(cfg, TruckPhase.DUMPING, duration)
        elif prev == TruckPhase.DUMPING:
            self.phase = TruckPhase.MOVING_EMPTY
        else:
            self.phase = TruckPhase.WAITING_LOADING
            self._begin_timed_phase(cfg, TruckPhase.WAITING_LOADING, self._sim_seconds(cfg))

        if self.phase in (TruckPhase.MOVING_LOADED, TruckPhase.MOVING_EMPTY, TruckPhase.REFUELING):
            self.road_progress = 0.0
            self.travel_condition_factor = sample_temporal_factor(self.rng)
            self.phase_seconds_left = 0.0
            self.phase_seconds_total = 0.0
        self._apply_motion(cfg)

    def _apply_motion(self, cfg) -> None:
        if not self.is_moving():
            self.speed_kmh = 0
            if self.phase == TruckPhase.LOADING:
                self.fuel_pct = max(0, self.fuel_pct - 0.02)
            elif self.phase == TruckPhase.REFUELING and self.road_progress >= 1.0:
                self.fuel_pct = min(100, self.fuel_pct + 0.5)
            return

        limit = min(cfg.truck_max_speed, self.road_speed_limit or cfg.truck_max_speed)
        loaded_grade_factor = 1.0
        if self.phase == TruckPhase.MOVING_LOADED:
            loaded_grade_factor = max(0.76, 1.0 - max(0.0, self.road_grade_pct) * 0.025)
        quality_factor = 0.82 + 0.18 * max(0.0, min(100.0, self.road_quality_score)) / 100.0
        combined = (
            self.baseline_travel_factor
            * self.travel_condition_factor
            * max(0.35, min(1.0, self.performance_factor))
            * loaded_grade_factor
            * quality_factor
        )
        limit *= max(0.3, min(1.08, combined))
        low = min(limit, max(5.0, limit * 0.72))
        self.speed_kmh = self.rng.uniform(low, max(low, limit))
        # Progress from distance and speed (sim tick advances tick_seconds * speed wall→sim)
        sim_hours = self._sim_seconds(cfg) / 3600.0
        dist = max(0.1, self.road_distance_km)
        delta = (self.speed_kmh * sim_hours) / dist
        self.road_progress = min(1.0, self.road_progress + delta)
        self.odometer_km += self.speed_kmh * sim_hours
        burn = 0.08 + (0.12 if self.payload_t > 50 else 0.04)
        burn *= max(1.0, self.fuel_rate_factor)
        self.fuel_pct = max(0, self.fuel_pct - self.rng.uniform(burn * 0.5, burn))
