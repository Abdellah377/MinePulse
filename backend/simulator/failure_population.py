"""Seeded simulator-only population of independent mechanical incidents.

This module owns synthetic scheduling and hidden profile labels.  It delegates
signal progression to the existing causal-scenario manager.  Only the resulting
telemetry, equipment states, OEM events, downtime and maintenance records are
persisted by the simulation engine.

Predictive-training incidents are not scheduled until the fleet has warmed up
(``warmup_min``, default 20 minutes). That warmup is fleet spin-up, not the
60-minute failure-risk lookback. The 60-minute observable precursor is produced
by degradation itself (70–110 minutes), so STOPPED_MECHANICAL cannot occur
until at least 70 minutes of scenario telemetry exist. Combined with warmup,
the earliest prototype stop is about 90 minutes after simulation start.
Genuine early stops, if they ever occurred, remain in the incident set and
simply do not count toward precursor coverage.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from simulator.causal_scenarios import CausalScenarioManager, ObservableTransition
from simulator.state_machine import TruckPhase, TruckRuntime


@dataclass(frozen=True)
class FailurePopulationConfig:
    enabled: bool = False
    warmup_min: float = 20.0
    spacing_min: float = 24.0
    spacing_max: float = 38.0
    degradation_min: float = 70.0
    degradation_max: float = 110.0
    repair_min: float = 20.0
    repair_max: float = 50.0
    max_concurrent: int = 4
    retry_min: float = 5.0
    profiles: tuple[str, ...] = (
        "lubrication_degradation",
        "lubrication_degradation",
        "lubrication_degradation",
        "cooling_degradation",
        "cooling_degradation",
        "cooling_degradation",
        "electrical_degradation",
        "electrical_degradation",
        "ambiguous_mechanical_degradation",
        "ambiguous_mechanical_degradation",
        "ambiguous_mechanical_degradation",
    )

    def __post_init__(self) -> None:
        if self.spacing_min <= 0 or self.spacing_max < self.spacing_min:
            raise ValueError("failure spacing range is invalid")
        if self.degradation_min <= 0 or self.degradation_max < self.degradation_min:
            raise ValueError("failure degradation range is invalid")
        if self.repair_min <= 0 or self.repair_max < self.repair_min:
            raise ValueError("failure repair range is invalid")
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        if not self.profiles:
            raise ValueError("at least one mechanical profile is required")


@dataclass
class PopulationIncident:
    run_id: str
    target_id: str
    profile_id: str
    started_at: datetime
    degradation_minutes: float
    repair_minutes: float
    incident_at: datetime | None = None
    recovery_due_at: datetime | None = None
    recovered_at: datetime | None = None


@dataclass(frozen=True)
class FailurePopulationUpdate:
    transitions: tuple[ObservableTransition, ...] = ()
    started: tuple[PopulationIncident, ...] = ()
    recovered: tuple[PopulationIncident, ...] = ()


class FailurePopulationManager:
    """Schedules balanced failures without exposing labels outside simulator QA."""

    def __init__(self, config: FailurePopulationConfig, *, seed: int) -> None:
        self.config = config
        self.seed = seed
        self.rng = random.Random(f"failure-population:{seed}")
        self.next_start_at: datetime | None = None
        self.active: dict[str, PopulationIncident] = {}
        self.history: list[PopulationIncident] = []
        self._target_counts: dict[str, int] = {}
        self._scheduling = config.enabled

    def reset(self) -> None:
        self.rng = random.Random(f"failure-population:{self.seed}")
        self.next_start_at = None
        self.active.clear()
        self.history.clear()
        self._target_counts.clear()
        self._scheduling = self.config.enabled

    def stop_scheduling(self) -> None:
        self._scheduling = False

    @property
    def has_active_incidents(self) -> bool:
        return bool(self.active)

    def advance(
        self,
        world,
        causal: CausalScenarioManager,
        sim_now: datetime,
    ) -> FailurePopulationUpdate:
        if not self.config.enabled:
            return FailurePopulationUpdate(transitions=tuple(causal.step(world, sim_now)))

        recovered = self._recover_due(world, causal, sim_now)
        started: list[PopulationIncident] = []
        if self.next_start_at is None:
            self.next_start_at = sim_now + timedelta(minutes=self.config.warmup_min)
        if self._scheduling and sim_now >= self.next_start_at:
            incident = self._start_one(world, causal, sim_now)
            if incident is not None:
                started.append(incident)
                spacing = self.rng.uniform(self.config.spacing_min, self.config.spacing_max)
                self.next_start_at = sim_now + timedelta(minutes=spacing)
            else:
                self.next_start_at = sim_now + timedelta(minutes=self.config.retry_min)

        transitions = tuple(causal.step(world, sim_now))
        for transition in transitions:
            incident = self.active.get(transition.run_id)
            if incident is None or transition.stage.value != "INCIDENT":
                continue
            if incident.incident_at is None:
                incident.incident_at = transition.occurred_at
                incident.recovery_due_at = transition.occurred_at + timedelta(
                    minutes=incident.repair_minutes
                )
        return FailurePopulationUpdate(
            transitions=transitions,
            started=tuple(started),
            recovered=tuple(recovered),
        )

    def _start_one(
        self,
        world,
        causal: CausalScenarioManager,
        sim_now: datetime,
    ) -> PopulationIncident | None:
        if len(self.active) >= self.config.max_concurrent:
            return None
        busy_targets = {run.target_id for run in causal.active.values()}
        available = [code for code in sorted(world.trucks) if code not in busy_targets]
        if not available:
            return None
        minimum = min(self._target_counts.get(code, 0) for code in available)
        least_used = [code for code in available if self._target_counts.get(code, 0) == minimum]
        target_id = self.rng.choice(least_used)
        profile_id = self.rng.choice(self.config.profiles)
        requested_minutes = self.rng.uniform(
            self.config.degradation_min, self.config.degradation_max
        )
        repair_minutes = self.rng.uniform(self.config.repair_min, self.config.repair_max)
        scenario_seed = self.rng.randrange(1, 2**31)
        run = causal.activate(
            world,
            profile_id,
            target_id,
            sim_now,
            duration_min=requested_minutes,
            seed=scenario_seed,
            profile_variant=(
                "ambiguous" if profile_id == "ambiguous_mechanical_degradation" else "clear"
            ),
        )
        incident = PopulationIncident(
            run_id=run.run_id,
            target_id=target_id,
            profile_id=profile_id,
            started_at=sim_now,
            degradation_minutes=run.duration_sec / 60.0,
            repair_minutes=repair_minutes,
        )
        self.active[run.run_id] = incident
        self.history.append(incident)
        self._target_counts[target_id] = self._target_counts.get(target_id, 0) + 1
        return incident

    def _recover_due(
        self,
        world,
        causal: CausalScenarioManager,
        sim_now: datetime,
    ) -> list[PopulationIncident]:
        recovered: list[PopulationIncident] = []
        for run_id, incident in list(self.active.items()):
            if incident.recovery_due_at is None or sim_now < incident.recovery_due_at:
                continue
            causal.stop(world, run_id)
            truck = world.trucks[incident.target_id]
            self._prepare_return_to_service(truck)
            incident.recovered_at = sim_now
            recovered.append(incident)
            del self.active[run_id]
        return recovered

    @staticmethod
    def _prepare_return_to_service(truck: TruckRuntime) -> None:
        truck.phase = TruckPhase.MOVING_EMPTY
        truck.payload_t = 0.0
        truck.road_progress = 0.0
        truck.speed_kmh = 0.0
        truck.reset_phase_timing()

    def developer_summary(self) -> dict:
        profile_counts: dict[str, int] = {}
        equipment_counts: dict[str, int] = {}
        for incident in self.history:
            profile_counts[incident.profile_id] = profile_counts.get(incident.profile_id, 0) + 1
            equipment_counts[incident.target_id] = equipment_counts.get(incident.target_id, 0) + 1
        return {
            "started": len(self.history),
            "recovered": sum(item.recovered_at is not None for item in self.history),
            "active": len(self.active),
            "profiles": dict(sorted(profile_counts.items())),
            "equipment": dict(sorted(equipment_counts.items())),
        }
