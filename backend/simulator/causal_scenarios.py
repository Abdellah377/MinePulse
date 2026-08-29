"""Simulator-only causal fault progression.

Hidden incident truth lives in this module.  The manager mutates normal simulator
runtime signals; the engine persists only telemetry, states, alerts and events.
Nothing in this module is imported by production operational or AI packages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
import random
from typing import Any
from uuid import uuid4

from simulator.loaders import LoaderRuntime
from simulator.state_machine import TruckPhase, TruckRuntime


class CausalStage(str, Enum):
    EARLY_DEGRADATION = "EARLY_DEGRADATION"
    MEASURABLE_SYMPTOMS = "MEASURABLE_SYMPTOMS"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    INCIDENT = "INCIDENT"


@dataclass(frozen=True)
class CausalScenarioSpec:
    scenario_id: str
    description: str
    target_kind: str
    hidden_root_cause: str
    default_duration_min: float
    observable_signals: tuple[str, ...]
    final_behavior: str


@dataclass(frozen=True)
class CausalSabotagePlan:
    """Simulator-only mapping from a requested test condition to a hidden profile."""

    scenario_id: str
    profile_variant: str
    final_alert_type: str


SCENARIO_SPECS: dict[str, CausalScenarioSpec] = {
    "lubrication_degradation": CausalScenarioSpec(
        scenario_id="lubrication_degradation",
        description="Progressive lubrication-system degradation",
        target_kind="TRUCK",
        hidden_root_cause="lubrication_system_degradation",
        default_duration_min=8.0,
        observable_signals=("oil_pressure_kpa", "engine_temp_c", "speed_kmh"),
        final_behavior="MECHANICAL_STOP",
    ),
    "cooling_degradation": CausalScenarioSpec(
        scenario_id="cooling_degradation",
        description="Progressive cooling-system degradation",
        target_kind="TRUCK",
        hidden_root_cause="cooling_system_degradation",
        default_duration_min=9.0,
        observable_signals=("engine_temp_c", "coolant_temp_c", "speed_kmh"),
        final_behavior="MECHANICAL_STOP",
    ),
    "tyre_degradation": CausalScenarioSpec(
        scenario_id="tyre_degradation",
        description="Progressive tyre-pressure loss",
        target_kind="TRUCK",
        hidden_root_cause="progressive_tyre_pressure_loss",
        default_duration_min=8.0,
        observable_signals=("tyre_pressure_kpa", "tyre_temp_c", "speed_kmh"),
        final_behavior="SAFE_STOP",
    ),
    "communication_degradation": CausalScenarioSpec(
        scenario_id="communication_degradation",
        description="Progressive communications-link deterioration",
        target_kind="TRUCK",
        hidden_root_cause="communications_link_deterioration",
        default_duration_min=7.0,
        observable_signals=("communication_quality", "telemetry_gaps"),
        final_behavior="CONNECTION_LOSS",
    ),
    "loader_bottleneck": CausalScenarioSpec(
        scenario_id="loader_bottleneck",
        description="Progressive loader-throughput bottleneck",
        target_kind="LOADER",
        hidden_root_cause="loader_performance_degradation",
        default_duration_min=10.0,
        observable_signals=("loading_duration", "queue_wait", "cycle_time", "production"),
        final_behavior="REDUCED_CAPACITY",
    ),
    "fuel_efficiency_degradation": CausalScenarioSpec(
        scenario_id="fuel_efficiency_degradation",
        description="Progressive fuel-efficiency and load-response degradation",
        target_kind="TRUCK",
        hidden_root_cause="fuel_efficiency_degradation",
        default_duration_min=8.0,
        observable_signals=(
            "fuel_rate_lph",
            "engine_load_pct",
            "engine_temp_c",
            "cycle_time",
        ),
        final_behavior="HIGH_FUEL_RATE",
    ),
    "ambiguous_stop": CausalScenarioSpec(
        scenario_id="ambiguous_stop",
        description="Unexplained operational stop with weak, non-diagnostic precursors",
        target_kind="TRUCK",
        hidden_root_cause="unresolved_operational_stop",
        default_duration_min=7.0,
        observable_signals=("speed_kmh", "communication_quality", "engine_temp_c"),
        final_behavior="UNDEFINED_STOP",
    ),
    "ambiguous_mechanical_degradation": CausalScenarioSpec(
        scenario_id="ambiguous_mechanical_degradation",
        description="Mixed weak degradation signals preceding a mechanical stop",
        target_kind="TRUCK",
        hidden_root_cause="unresolved_mechanical_degradation",
        default_duration_min=8.0,
        observable_signals=(
            "oil_pressure_kpa",
            "engine_temp_c",
            "communication_quality",
            "speed_kmh",
        ),
        final_behavior="MECHANICAL_STOP",
    ),
}


_DIRECT_SABOTAGE_SCENARIOS: dict[str, tuple[str, str]] = {
    "COMMUNICATION_LOSS": ("communication_degradation", "COMMUNICATION_LOSS"),
    "HIGH_ENGINE_TEMPERATURE": ("cooling_degradation", "EQUIPMENT_MECHANICAL_STOP"),
    "LOW_OIL_PRESSURE": ("lubrication_degradation", "EQUIPMENT_MECHANICAL_STOP"),
    "TYRE_PRESSURE_LOW": ("tyre_degradation", "EQUIPMENT_SAFETY_STOP"),
    "TYRE_TEMPERATURE_HIGH": ("tyre_degradation", "EQUIPMENT_SAFETY_STOP"),
    "FUEL_RATE_HIGH": ("fuel_efficiency_degradation", "FUEL_CONSUMPTION_ANOMALY"),
    "STOP_UNDEFINED": ("ambiguous_stop", "UNEXPLAINED_STOP"),
    "SENSOR_SIGNAL_LOSS": ("communication_degradation", "COMMUNICATION_LOSS"),
}


def causal_plan_for_sabotage(
    action: str,
    target_kind: str,
    *,
    seed: int,
    requested_profile: str | None = None,
) -> CausalSabotagePlan | None:
    """Resolve a manual sabotage into a reproducible hidden causal profile."""
    action = action.upper()
    if target_kind != "TRUCK":
        return None
    if action == "MECHANICAL_BREAKDOWN":
        aliases = {
            "lubrication": ("lubrication_degradation", "clear"),
            "cooling": ("cooling_degradation", "clear"),
            "ambiguous": ("ambiguous_mechanical_degradation", "ambiguous"),
            "inconclusive": ("ambiguous_mechanical_degradation", "inconclusive"),
        }
        if requested_profile:
            try:
                scenario_id, variant = aliases[requested_profile.casefold()]
            except KeyError as exc:
                raise ValueError(
                    "Mechanical profile must be lubrication, cooling, ambiguous, or inconclusive"
                ) from exc
        else:
            # Ten stable slots: seven clear, two ambiguous, one intentionally
            # inconclusive. Explicit seeds make tests and demos replayable.
            scenario_id, variant = (
                [("lubrication_degradation", "clear")] * 4
                + [("cooling_degradation", "clear")] * 3
                + [("ambiguous_mechanical_degradation", "ambiguous")] * 2
                + [("ambiguous_mechanical_degradation", "inconclusive")]
            )[seed % 10]
        return CausalSabotagePlan(
            scenario_id=scenario_id,
            profile_variant=variant,
            final_alert_type="EQUIPMENT_MECHANICAL_STOP",
        )
    direct = _DIRECT_SABOTAGE_SCENARIOS.get(action)
    if not direct:
        return None
    scenario_id, alert_type = direct
    return CausalSabotagePlan(
        scenario_id=scenario_id,
        profile_variant="ambiguous" if action == "STOP_UNDEFINED" else "clear",
        final_alert_type=alert_type,
    )


@dataclass(frozen=True)
class ObservableTransition:
    """A simulator-engine instruction containing no hidden causal label."""

    run_id: str
    target_id: str
    occurred_at: datetime
    stage: CausalStage
    event_kind: str
    alert_type: str | None = None
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    maintenance_required: bool = False

    def operational_payload(self) -> dict[str, Any]:
        """Fields safe to persist as observable operational records."""
        return {
            "target_id": self.target_id,
            "occurred_at": self.occurred_at.isoformat(),
            "event_kind": self.event_kind,
            "alert_type": self.alert_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "maintenance_required": self.maintenance_required,
        }


@dataclass
class CausalTraceSample:
    ts: datetime
    stage: CausalStage
    progress: float
    observable_values: dict[str, float | bool | str | None]


@dataclass
class ActiveCausalScenario:
    run_id: str
    scenario_id: str
    target_id: str
    target_kind: str
    hidden_root_cause: str
    started_at: datetime
    duration_sec: float
    seed: int
    variability: dict[str, Any]
    original_state: dict[str, Any]
    profile_variant: str = "clear"
    stage: CausalStage | None = None
    progress: float = 0.0
    last_step_at: datetime | None = None
    incident_at: datetime | None = None
    trace: list[CausalTraceSample] = field(default_factory=list)

    def developer_status(self, *, include_hidden: bool) -> dict[str, Any]:
        data = {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "started_at": self.started_at.isoformat(),
            "duration_sec": round(self.duration_sec, 1),
            "seed": self.seed,
            "stage": self.stage.value if self.stage else None,
            "progress": round(self.progress, 4),
            "incident_at": self.incident_at.isoformat() if self.incident_at else None,
        }
        if include_hidden:
            data["hidden_root_cause"] = self.hidden_root_cause
            data["profile_variant"] = self.profile_variant
        return data


def _stage_for(progress: float) -> CausalStage:
    if progress < 0.25:
        return CausalStage.EARLY_DEGRADATION
    if progress < 0.55:
        return CausalStage.MEASURABLE_SYMPTOMS
    if progress < 0.75:
        return CausalStage.WARNING
    if progress < 0.92:
        return CausalStage.CRITICAL
    return CausalStage.INCIDENT


def _capture_truck(truck: TruckRuntime) -> dict[str, Any]:
    return {
        "phase": truck.phase.value,
        "pre_stop_phase": truck.pre_stop_phase.value if truck.pre_stop_phase else None,
        "speed_kmh": truck.speed_kmh,
        "mechanical_hold": truck.mechanical_hold,
        "unexplained_hold": truck.unexplained_hold,
        "in_maintenance": truck.in_maintenance,
        "comm_lost": truck.comm_lost,
        "sensor_signal_loss": truck.sensor_signal_loss,
        "performance_factor": truck.performance_factor,
        "fuel_rate_factor": truck.fuel_rate_factor,
        "scenario_oil_pressure_target": truck.scenario_oil_pressure_target,
        "scenario_engine_temp_target": truck.scenario_engine_temp_target,
        "scenario_coolant_temp_target": truck.scenario_coolant_temp_target,
        "scenario_comm_quality_target": truck.scenario_comm_quality_target,
        "scenario_tyre_pressure_target": truck.scenario_tyre_pressure_target,
        "scenario_tyre_temp_target": truck.scenario_tyre_temp_target,
        "tyre_fault_position": truck.tyre_fault_position,
    }


def _capture_loader(loader: LoaderRuntime) -> dict[str, Any]:
    return {
        "available": loader.available,
        "capacity_factor": loader.capacity_factor,
        "slow_loading": loader.slow_loading,
        "mechanical_breakdown": loader.mechanical_breakdown,
    }


class CausalScenarioManager:
    """Owns hidden scenario state and applies bounded effects over simulator time."""

    def __init__(self) -> None:
        self.active: dict[str, ActiveCausalScenario] = {}

    def activate(
        self,
        world,
        scenario_id: str,
        target_id: str,
        sim_now: datetime,
        *,
        duration_min: float | None = None,
        seed: int = 42,
        profile_variant: str = "clear",
    ) -> ActiveCausalScenario:
        try:
            spec = SCENARIO_SPECS[scenario_id]
        except KeyError as exc:
            raise ValueError(f"Unknown causal scenario: {scenario_id}") from exc
        if any(run.target_id == target_id for run in self.active.values()):
            raise ValueError(f"Target {target_id} already has an active causal scenario")
        entity = self._entity(world, spec.target_kind, target_id)
        rng = random.Random(seed)
        requested_duration = duration_min or spec.default_duration_min
        if requested_duration <= 0:
            raise ValueError("duration_min must be positive")
        duration_sec = max(60.0, requested_duration * 60.0 * rng.uniform(0.96, 1.04))
        variability = {
            "sensor_bias": rng.uniform(-0.015, 0.015),
            "thermal_bias": rng.uniform(-1.5, 1.5),
            "pressure_bias": rng.uniform(-8.0, 8.0),
            "gap_phase": float(rng.randrange(3)),
        }
        original = _capture_truck(entity) if spec.target_kind == "TRUCK" else _capture_loader(entity)
        run = ActiveCausalScenario(
            run_id=f"causal-{uuid4()}",
            scenario_id=scenario_id,
            target_id=target_id,
            target_kind=spec.target_kind,
            hidden_root_cause=spec.hidden_root_cause,
            started_at=sim_now,
            duration_sec=duration_sec,
            seed=seed,
            variability=variability,
            original_state=original,
            profile_variant=profile_variant,
        )
        self.active[run.run_id] = run
        return run

    def step(self, world, sim_now: datetime) -> list[ObservableTransition]:
        transitions: list[ObservableTransition] = []
        for run in self.active.values():
            if run.last_step_at and sim_now < run.last_step_at:
                raise ValueError("Causal scenario timestamp moved backwards")
            elapsed = max(0.0, (sim_now - run.started_at).total_seconds())
            progress = min(1.0, elapsed / run.duration_sec)
            stage = _stage_for(progress)
            entity = self._entity(world, run.target_kind, run.target_id)
            self._apply_effect(run, entity, progress, sim_now)
            if stage != run.stage:
                transitions.extend(self._transitions_for_stage(run, stage, sim_now))
            run.stage = stage
            run.progress = progress
            run.last_step_at = sim_now
            run.trace.append(
                CausalTraceSample(
                    ts=sim_now,
                    stage=stage,
                    progress=progress,
                    observable_values=self._observable_values(run, entity),
                )
            )
            if stage == CausalStage.INCIDENT and run.incident_at is None:
                run.incident_at = sim_now
        return transitions

    def stop(self, world, run_id: str) -> ActiveCausalScenario:
        try:
            run = self.active.pop(run_id)
        except KeyError as exc:
            raise ValueError(f"Unknown active causal scenario: {run_id}") from exc
        entity = self._entity(world, run.target_kind, run.target_id)
        self._restore(run, entity)
        return run

    def reset(self, world) -> None:
        for run_id in list(self.active):
            self.stop(world, run_id)

    def developer_status(self, *, include_hidden: bool = True) -> list[dict[str, Any]]:
        return [
            run.developer_status(include_hidden=include_hidden)
            for run in sorted(self.active.values(), key=lambda item: item.started_at)
        ]

    @staticmethod
    def _entity(world, target_kind: str, target_id: str):
        entity = world.trucks.get(target_id) if target_kind == "TRUCK" else world.loaders.get(target_id)
        if entity is None:
            raise ValueError(f"{target_kind} target {target_id} does not exist")
        return entity

    @staticmethod
    def _apply_effect(
        run: ActiveCausalScenario,
        entity: TruckRuntime | LoaderRuntime,
        progress: float,
        sim_now: datetime,
    ) -> None:
        bias = run.variability
        if run.scenario_id == "lubrication_degradation":
            truck = entity
            assert isinstance(truck, TruckRuntime)
            truck.scenario_oil_pressure_target = max(
                105.0, 425.0 - 315.0 * progress + bias["pressure_bias"]
            )
            truck.scenario_engine_temp_target = 91.0 + 20.0 * progress + bias["thermal_bias"]
            truck.performance_factor = max(0.62, 1.0 - 0.36 * progress)
            if progress >= 0.92:
                truck.pre_stop_phase = truck.pre_stop_phase or truck.phase
                truck.mechanical_hold = True
        elif run.scenario_id == "cooling_degradation":
            truck = entity
            assert isinstance(truck, TruckRuntime)
            truck.scenario_engine_temp_target = 88.0 + 29.0 * progress + bias["thermal_bias"]
            truck.scenario_coolant_temp_target = 82.0 + 29.0 * progress + bias["thermal_bias"]
            truck.performance_factor = max(0.58, 1.0 - 0.42 * progress)
            if progress >= 0.92:
                truck.pre_stop_phase = truck.pre_stop_phase or truck.phase
                truck.mechanical_hold = True
        elif run.scenario_id == "tyre_degradation":
            truck = entity
            assert isinstance(truck, TruckRuntime)
            truck.tyre_fault_position = truck.tyre_fault_position or "FL"
            truck.scenario_tyre_pressure_target = max(
                360.0, 705.0 - 350.0 * progress + bias["pressure_bias"]
            )
            truck.scenario_tyre_temp_target = 46.0 + 45.0 * progress + bias["thermal_bias"]
            truck.performance_factor = max(0.55, 1.0 - 0.45 * progress)
            if progress >= 0.92:
                truck.pre_stop_phase = truck.pre_stop_phase or truck.phase
                truck.in_maintenance = True
        elif run.scenario_id == "communication_degradation":
            truck = entity
            assert isinstance(truck, TruckRuntime)
            truck.scenario_comm_quality_target = max(
                8.0, 96.0 - 90.0 * progress + 100.0 * bias["sensor_bias"]
            )
            if 0.58 <= progress < 0.92:
                tick_index = int((sim_now - run.started_at).total_seconds() // 30)
                truck.sensor_signal_loss = (tick_index + int(bias["gap_phase"])) % 3 == 0
            else:
                truck.sensor_signal_loss = False
            if progress >= 0.92:
                truck.pre_stop_phase = truck.pre_stop_phase or truck.phase
                truck.comm_lost = True
        elif run.scenario_id == "loader_bottleneck":
            loader = entity
            assert isinstance(loader, LoaderRuntime)
            loader.available = True
            loader.mechanical_breakdown = False
            loader.capacity_factor = max(0.25, 1.0 - 0.75 * progress)
            loader.slow_loading = progress >= 0.25
        elif run.scenario_id == "fuel_efficiency_degradation":
            truck = entity
            assert isinstance(truck, TruckRuntime)
            truck.fuel_rate_factor = 1.0 + 1.25 * progress + bias["sensor_bias"]
            truck.performance_factor = max(0.78, 1.0 - 0.22 * progress)
            truck.scenario_engine_temp_target = 88.0 + 13.0 * progress + bias["thermal_bias"]
            truck.scenario_coolant_temp_target = 82.0 + 10.0 * progress + bias["thermal_bias"]
            truck.scenario_oil_pressure_target = 425.0 - 35.0 * progress + bias["pressure_bias"]
        elif run.scenario_id == "ambiguous_stop":
            truck = entity
            assert isinstance(truck, TruckRuntime)
            truck.performance_factor = max(0.86, 1.0 - 0.14 * progress)
            truck.scenario_engine_temp_target = 87.0 + 6.0 * progress + bias["thermal_bias"]
            truck.scenario_comm_quality_target = 96.0 - 14.0 * progress
            if 0.55 <= progress < 0.82:
                tick_index = int((sim_now - run.started_at).total_seconds() // 30)
                truck.sensor_signal_loss = (tick_index + int(bias["gap_phase"])) % 5 == 0
            else:
                truck.sensor_signal_loss = False
            if progress >= 0.92:
                truck.pre_stop_phase = truck.pre_stop_phase or truck.phase
                truck.unexplained_hold = True
        elif run.scenario_id == "ambiguous_mechanical_degradation":
            truck = entity
            assert isinstance(truck, TruckRuntime)
            strength = 0.55 if run.profile_variant == "inconclusive" else 1.0
            truck.scenario_oil_pressure_target = (
                425.0 - 88.0 * progress * strength + bias["pressure_bias"]
            )
            truck.scenario_engine_temp_target = (
                88.0 + 12.0 * progress * strength + bias["thermal_bias"]
            )
            truck.scenario_comm_quality_target = 96.0 - 11.0 * progress * strength
            truck.performance_factor = max(0.74, 1.0 - 0.26 * progress * strength)
            if progress >= 0.92:
                truck.pre_stop_phase = truck.pre_stop_phase or truck.phase
                truck.mechanical_hold = True

    @staticmethod
    def _observable_values(
        run: ActiveCausalScenario,
        entity: TruckRuntime | LoaderRuntime,
    ) -> dict[str, float | bool | str | None]:
        if isinstance(entity, LoaderRuntime):
            return {
                "capacity_factor": round(entity.capacity_factor, 4),
                "slow_loading": entity.slow_loading,
            }
        return {
            "oil_pressure_target_kpa": entity.scenario_oil_pressure_target,
            "engine_temp_target_c": entity.scenario_engine_temp_target,
            "coolant_temp_target_c": entity.scenario_coolant_temp_target,
            "communication_quality_target": entity.scenario_comm_quality_target,
            "tyre_pressure_target_kpa": entity.scenario_tyre_pressure_target,
            "tyre_temp_target_c": entity.scenario_tyre_temp_target,
            "performance_factor": round(entity.performance_factor, 4),
            "fuel_rate_factor": round(entity.fuel_rate_factor, 4),
            "telemetry_gap": entity.sensor_signal_loss or entity.comm_lost,
            "operational_state": entity.phase.value,
        }

    @staticmethod
    def _transitions_for_stage(
        run: ActiveCausalScenario,
        stage: CausalStage,
        sim_now: datetime,
    ) -> list[ObservableTransition]:
        if stage == CausalStage.WARNING:
            return [
                ObservableTransition(
                    run_id=run.run_id,
                    target_id=run.target_id,
                    occurred_at=sim_now,
                    stage=stage,
                    event_kind="WARNING_STAGE_REACHED",
                )
            ]
        if stage != CausalStage.INCIDENT:
            return []
        if run.scenario_id == "communication_degradation":
            return [
                ObservableTransition(
                    run_id=run.run_id,
                    target_id=run.target_id,
                    occurred_at=sim_now,
                    stage=stage,
                    event_kind="CONNECTION_LOSS",
                    alert_type="COMMUNICATION_LOSS",
                    title=f"{run.target_id} perte de communication",
                    description=f"{run.target_id} — télémétrie interrompue après une qualité de liaison dégradée.",
                    severity="WARNING",
                )
            ]
        if run.scenario_id == "loader_bottleneck":
            return [
                ObservableTransition(
                    run_id=run.run_id,
                    target_id=run.target_id,
                    occurred_at=sim_now,
                    stage=stage,
                    event_kind="LOADING_PERFORMANCE_DEGRADED",
                    alert_type="LOADING_PERFORMANCE_DEGRADED",
                    title=f"{run.target_id} performance de chargement dégradée",
                    description="Allongement persistant des opérations de chargement et des files associées.",
                    severity="WARNING",
                )
            ]
        if run.scenario_id == "fuel_efficiency_degradation":
            return [
                ObservableTransition(
                    run_id=run.run_id,
                    target_id=run.target_id,
                    occurred_at=sim_now,
                    stage=stage,
                    event_kind="FUEL_CONSUMPTION_ANOMALY",
                    alert_type="FUEL_CONSUMPTION_ANOMALY",
                    title=f"{run.target_id} consommation carburant anormale",
                    description="Consommation élevée après une dégradation progressive du rendement opérationnel.",
                    severity="WARNING",
                )
            ]
        if run.scenario_id == "ambiguous_stop":
            return [
                ObservableTransition(
                    run_id=run.run_id,
                    target_id=run.target_id,
                    occurred_at=sim_now,
                    stage=stage,
                    event_kind="UNEXPLAINED_STOP",
                    alert_type="UNEXPLAINED_STOP",
                    title=f"{run.target_id} arrêt non défini",
                    description=f"{run.target_id} arrêté — cause non confirmée par les données disponibles.",
                    severity="WARNING",
                )
            ]
        if run.scenario_id == "ambiguous_mechanical_degradation":
            return [
                ObservableTransition(
                    run_id=run.run_id,
                    target_id=run.target_id,
                    occurred_at=sim_now,
                    stage=stage,
                    event_kind="MECHANICAL_STOP",
                    alert_type="EQUIPMENT_MECHANICAL_STOP",
                    title=f"{run.target_id} arrêt mécanique",
                    description=f"{run.target_id} immobilisé — cause précise non confirmée.",
                    severity="CRITICAL",
                    maintenance_required=True,
                )
            ]
        if run.scenario_id == "tyre_degradation":
            return [
                ObservableTransition(
                    run_id=run.run_id,
                    target_id=run.target_id,
                    occurred_at=sim_now,
                    stage=stage,
                    event_kind="SAFETY_STOP",
                    alert_type="EQUIPMENT_SAFETY_STOP",
                    title=f"{run.target_id} arrêt de sécurité",
                    description=f"{run.target_id} immobilisé après dégradation progressive d'un paramètre surveillé.",
                    severity="CRITICAL",
                    maintenance_required=True,
                )
            ]
        return [
            ObservableTransition(
                run_id=run.run_id,
                target_id=run.target_id,
                occurred_at=sim_now,
                stage=stage,
                event_kind="MECHANICAL_STOP",
                alert_type="EQUIPMENT_MECHANICAL_STOP",
                title=f"{run.target_id} arrêt mécanique",
                description=f"{run.target_id} immobilisé après une dégradation mesurable des paramètres moteur.",
                severity="CRITICAL",
                maintenance_required=True,
            )
        ]

    @staticmethod
    def _restore(run: ActiveCausalScenario, entity: TruckRuntime | LoaderRuntime) -> None:
        original = run.original_state
        if isinstance(entity, LoaderRuntime):
            entity.available = original["available"]
            entity.capacity_factor = original["capacity_factor"]
            entity.slow_loading = original["slow_loading"]
            entity.mechanical_breakdown = original["mechanical_breakdown"]
            return
        entity.mechanical_hold = original["mechanical_hold"]
        entity.unexplained_hold = original.get("unexplained_hold", False)
        entity.in_maintenance = original["in_maintenance"]
        entity.comm_lost = original["comm_lost"]
        entity.sensor_signal_loss = original["sensor_signal_loss"]
        entity.performance_factor = original["performance_factor"]
        entity.fuel_rate_factor = original.get("fuel_rate_factor", 1.0)
        entity.scenario_oil_pressure_target = original["scenario_oil_pressure_target"]
        entity.scenario_engine_temp_target = original["scenario_engine_temp_target"]
        entity.scenario_coolant_temp_target = original["scenario_coolant_temp_target"]
        entity.scenario_comm_quality_target = original["scenario_comm_quality_target"]
        entity.scenario_tyre_pressure_target = original["scenario_tyre_pressure_target"]
        entity.scenario_tyre_temp_target = original["scenario_tyre_temp_target"]
        entity.tyre_fault_position = original["tyre_fault_position"]
        entity.pre_stop_phase = None
        try:
            entity.phase = TruckPhase(original["phase"])
        except ValueError:
            entity.phase = TruckPhase.WAITING_LOADING
        entity.speed_kmh = original["speed_kmh"]
        entity.reset_phase_timing()


def validate_trace(run: ActiveCausalScenario) -> list[str]:
    """Return simulator-data warnings without classifying AI quality."""
    warnings: list[str] = []
    if not run.trace:
        return ["Scenario produced no observable samples."]
    for previous, current in zip(run.trace, run.trace[1:]):
        if current.ts <= previous.ts:
            warnings.append("Scenario samples contain duplicate or backwards timestamps.")
        if current.progress < previous.progress:
            warnings.append("Scenario progression moved backwards.")
        for key in set(previous.observable_values).intersection(current.observable_values):
            left = previous.observable_values[key]
            right = current.observable_values[key]
            if not isinstance(left, (int, float)) or isinstance(left, bool):
                continue
            if not isinstance(right, (int, float)) or isinstance(right, bool):
                continue
            limits = {
                "oil_pressure_target_kpa": 80.0,
                "engine_temp_target_c": 10.0,
                "coolant_temp_target_c": 10.0,
                "communication_quality_target": 25.0,
                "tyre_pressure_target_kpa": 90.0,
                "tyre_temp_target_c": 12.0,
                "capacity_factor": 0.2,
            }
            limit = limits.get(key)
            if limit is not None and abs(float(right) - float(left)) > limit:
                warnings.append(f"Unrealistic abrupt progression for {key}.")
    stages = [sample.stage for sample in run.trace]
    if CausalStage.INCIDENT in stages and CausalStage.WARNING not in stages:
        warnings.append("Incident occurred without a preceding warning stage.")
    return list(dict.fromkeys(warnings))


def scenario_catalog(*, include_hidden: bool = False) -> list[dict[str, Any]]:
    rows = []
    for spec in SCENARIO_SPECS.values():
        row = asdict(spec)
        if not include_hidden:
            row.pop("hidden_root_cause", None)
        rows.append(row)
    return rows
