"""Scenario lifecycle — ground truth only, no AI conclusions.

Each scenario supports scheduled start, optional duration, active state, effect, and recovery.
Deterministic under SIMULATION_RANDOM_SEED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from simulator.clock import get_sim_logger
from simulator.state_machine import TruckPhase
from simulator.world import SimWorld

log = get_sim_logger()


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    start_min: int  # minutes from midnight
    duration_min: int | None  # None = permanent until reset
    description: str


SPECS: dict[str, ScenarioSpec] = {
    "comm_loss": ScenarioSpec(
        id="comm_loss",
        start_min=6 * 60 + 20,
        duration_min=7,
        description="TRK-004 communication loss",
    ),
    "exc_breakdown": ScenarioSpec(
        id="exc_breakdown",
        start_min=6 * 60 + 31,
        duration_min=40,
        description="EXC-002 mechanical breakdown",
    ),
    "unexplained_stop": ScenarioSpec(
        id="unexplained_stop",
        start_min=6 * 60 + 45,
        duration_min=15,
        description="TRK-012 unexplained stop",
    ),
}


def _minute_of_day(sim_now: datetime) -> int:
    return sim_now.hour * 60 + sim_now.minute


def apply_scenarios(world: SimWorld, sim_now: datetime, scenario: str) -> list[str]:
    """Apply start/recovery. Returns list of newly started event ids (for side effects)."""
    if scenario == "normal":
        return []

    t = _minute_of_day(sim_now)
    newly_started: list[str] = []
    spec = SPECS.get(scenario)
    if not spec:
        return []

    # Start
    if t >= spec.start_min and f"{spec.id}:start" not in world.scenario_events_fired:
        world.scenario_events_fired.add(f"{spec.id}:start")
        ends = None if spec.duration_min is None else spec.start_min + spec.duration_min
        world.scenario_active[spec.id] = {"ends_at_min": ends}
        newly_started.append(spec.id)
        _inject_start(world, spec.id)
        log.info("%s started", spec.description)

    # Recovery
    active = world.scenario_active.get(spec.id)
    if active and f"{spec.id}:recover" not in world.scenario_events_fired:
        ends = active.get("ends_at_min")
        if ends is not None and t >= ends:
            world.scenario_events_fired.add(f"{spec.id}:recover")
            _inject_recover(world, spec.id)
            world.scenario_active.pop(spec.id, None)
            log.info("%s recovered", spec.description)

    return newly_started


def _inject_start(world: SimWorld, sid: str) -> None:
    if sid == "exc_breakdown":
        world.excavators_down.add("EXC-002")
    elif sid == "comm_loss":
        trk = world.trucks.get("TRK-004")
        if trk:
            trk.comm_lost = True
            trk.phase = TruckPhase.NO_COMM
            trk.speed_kmh = 0
    elif sid == "unexplained_stop":
        trk = world.trucks.get("TRK-012")
        if trk:
            trk.pre_stop_phase = trk.phase
            trk.unexplained_hold = True
            trk.phase = TruckPhase.STOPPED
            trk.speed_kmh = 0


def _inject_recover(world: SimWorld, sid: str) -> None:
    if sid == "exc_breakdown":
        world.excavators_down.discard("EXC-002")
    elif sid == "comm_loss":
        trk = world.trucks.get("TRK-004")
        if trk:
            trk.comm_lost = False
            trk.phase = TruckPhase.WAITING_LOADING
            trk.phase_ticks_left = 5
    elif sid == "unexplained_stop":
        trk = world.trucks.get("TRK-012")
        if trk:
            trk.unexplained_hold = False
            trk.phase = trk.pre_stop_phase or TruckPhase.MOVING_EMPTY
            trk.pre_stop_phase = None
            trk.phase_ticks_left = 5
