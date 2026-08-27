"""Deterministic, zero-cost tests for simulator-only causal progression."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.oem.thresholds import classify_value
from simulator.causal_scenarios import (
    CausalScenarioManager,
    CausalStage,
    SCENARIO_SPECS,
    causal_plan_for_sabotage,
    scenario_catalog,
    validate_trace,
)
from simulator.apply_commands import CommandContext, _apply_command
from simulator.commands import SimulationCommand
from simulator.generators.telemetry import build_telemetry
from simulator.generators.tyres import tyre_rows
from simulator.loaders import LoaderRuntime
from simulator.state_machine import TruckPhase, TruckRuntime


NOW = datetime(2026, 1, 29, 6, 0, tzinfo=timezone.utc)


def _world() -> SimpleNamespace:
    world = SimpleNamespace(
        trucks={
            f"TRK-{index:03d}": TruckRuntime(
                code=f"TRK-{index:03d}",
                equipment_id=index,
                phase=TruckPhase.MOVING_EMPTY,
            )
            for index in range(1, 6)
        },
        loaders={
            "EXC-001": LoaderRuntime(code="EXC-001", equipment_id=101),
        },
    )
    world.injections = {}
    world.ground_truth = []
    world.add_injection = lambda injection: world.injections.update(
        {injection.injection_id: injection}
    )
    world.log_test = lambda *_args, **_kwargs: None
    world.log_sim = lambda *_args, **_kwargs: None
    return world


def _times(run) -> list[datetime]:
    return [
        run.started_at + timedelta(seconds=run.duration_sec * fraction)
        for fraction in (0.0, 0.18, 0.32, 0.48, 0.62, 0.78, 0.93, 1.0)
    ]


def _complete(manager: CausalScenarioManager, world, run):
    transitions = []
    for ts in _times(run):
        transitions.extend(manager.step(world, ts))
    return transitions


@pytest.mark.parametrize(
    ("scenario_id", "target_id"),
    [
        ("lubrication_degradation", "TRK-001"),
        ("cooling_degradation", "TRK-002"),
        ("tyre_degradation", "TRK-003"),
        ("communication_degradation", "TRK-004"),
        ("loader_bottleneck", "EXC-001"),
        ("fuel_efficiency_degradation", "TRK-001"),
        ("ambiguous_stop", "TRK-002"),
        ("ambiguous_mechanical_degradation", "TRK-003"),
    ],
)
def test_all_causal_scenarios_progress_through_warning_before_incident(
    scenario_id,
    target_id,
):
    world = _world()
    manager = CausalScenarioManager()
    run = manager.activate(world, scenario_id, target_id, NOW, seed=71)
    transitions = _complete(manager, world, run)

    assert run.stage == CausalStage.INCIDENT
    assert run.incident_at is not None
    assert CausalStage.WARNING in [sample.stage for sample in run.trace]
    assert [item.stage for item in transitions][-1] == CausalStage.INCIDENT
    assert validate_trace(run) == []


def test_lubrication_scenario_creates_gradual_threshold_crossing_and_stop():
    world = _world()
    truck = world.trucks["TRK-001"]
    manager = CausalScenarioManager()
    run = manager.activate(world, "lubrication_degradation", truck.code, NOW, seed=11)
    observed = []
    stages = []
    cfg = SimpleNamespace(tick_seconds=1.0, speed=30.0)
    for index in range(18):
        ts = NOW + timedelta(seconds=run.duration_sec * index / 17)
        manager.step(world, ts)
        telemetry = build_telemetry(truck)
        observed.append(float(telemetry["oil_pressure_kpa"]))
        stages.append(run.stage)

    assert observed[0] > observed[-1]
    assert observed[0] - observed[1] < 80
    first_alarm = next(i for i, value in enumerate(observed) if classify_value("oil_pressure_kpa", value))
    assert stages[first_alarm] in {CausalStage.WARNING, CausalStage.CRITICAL, CausalStage.INCIDENT}
    assert truck.mechanical_hold
    truck.advance_phase(cfg)
    assert truck.phase == TruckPhase.STOPPED


def test_cooling_and_tyre_scenarios_generate_ordered_sensor_trends():
    world = _world()
    manager = CausalScenarioManager()
    cooling = manager.activate(world, "cooling_degradation", "TRK-002", NOW, seed=4)
    tyre = manager.activate(world, "tyre_degradation", "TRK-003", NOW, seed=5)
    engine_temps = []
    tyre_pressures = []
    for fraction in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        ts = NOW + timedelta(seconds=max(cooling.duration_sec, tyre.duration_sec) * fraction)
        manager.step(world, ts)
        engine_temps.append(float(build_telemetry(world.trucks["TRK-002"])["engine_temp_c"]))
        fl = next(row for row in tyre_rows(world.trucks["TRK-003"]) if row["position"] == "FL")
        tyre_pressures.append(float(fl["pressure_kpa"]))

    assert engine_temps[-1] > engine_temps[0]
    assert tyre_pressures[-1] < tyre_pressures[0]
    assert classify_value("tyre_pressure_kpa", tyre_pressures[-1]) is not None
    assert world.trucks["TRK-003"].in_maintenance


def test_communication_degradation_never_claims_mechanical_failure():
    world = _world()
    manager = CausalScenarioManager()
    run = manager.activate(world, "communication_degradation", "TRK-004", NOW, seed=22)
    transitions = _complete(manager, world, run)
    truck = world.trucks["TRK-004"]

    assert any(sample.observable_values["telemetry_gap"] for sample in run.trace)
    assert truck.comm_lost
    assert not truck.mechanical_hold
    incident = transitions[-1]
    assert incident.alert_type == "COMMUNICATION_LOSS"
    assert "mechan" not in str(incident.operational_payload()).casefold()


def test_loader_bottleneck_reduces_capacity_without_mechanical_breakdown():
    world = _world()
    loader = world.loaders["EXC-001"]
    manager = CausalScenarioManager()
    run = manager.activate(world, "loader_bottleneck", loader.code, NOW, seed=9)
    _complete(manager, world, run)

    assert 0.2 <= loader.capacity_factor <= 0.3
    assert loader.slow_loading
    assert loader.available
    assert not loader.mechanical_breakdown


def test_seeded_progression_is_reproducible():
    worlds = [_world(), _world()]
    managers = [CausalScenarioManager(), CausalScenarioManager()]
    runs = [
        managers[i].activate(
            worlds[i], "lubrication_degradation", "TRK-001", NOW, seed=123
        )
        for i in range(2)
    ]
    for manager, world, run in zip(managers, worlds, runs):
        _complete(manager, world, run)

    assert runs[0].duration_sec == runs[1].duration_sec
    assert runs[0].variability == runs[1].variability
    assert [sample.observable_values for sample in runs[0].trace] == [
        sample.observable_values for sample in runs[1].trace
    ]


def test_stop_and_reset_restore_original_runtime_state():
    world = _world()
    truck = world.trucks["TRK-001"]
    original_phase = truck.phase
    manager = CausalScenarioManager()
    run = manager.activate(world, "lubrication_degradation", truck.code, NOW)
    _complete(manager, world, run)
    manager.stop(world, run.run_id)

    assert truck.phase == original_phase
    assert truck.scenario_oil_pressure_target is None
    assert truck.performance_factor == 1.0
    assert not truck.mechanical_hold
    assert manager.active == {}


def test_hidden_truth_is_absent_from_observable_payloads_and_public_catalog():
    world = _world()
    manager = CausalScenarioManager()
    run = manager.activate(world, "lubrication_degradation", "TRK-001", NOW)
    transitions = _complete(manager, world, run)
    serialized = str([item.operational_payload() for item in transitions]).casefold()

    assert run.hidden_root_cause.casefold() not in serialized
    assert "hidden_root_cause" not in serialized
    assert all("hidden_root_cause" not in item for item in scenario_catalog())
    assert "hidden_root_cause" in scenario_catalog(include_hidden=True)[0]


def test_production_ai_still_has_no_simulator_imports():
    backend = Path(__file__).resolve().parents[1]
    for path in (backend / "app" / "ai").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not item.name.startswith("simulator") for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("simulator")


def test_scenario_catalog_contains_diagnostic_and_manual_sabotage_profiles():
    assert set(SCENARIO_SPECS) == {
        "lubrication_degradation",
        "cooling_degradation",
        "tyre_degradation",
        "communication_degradation",
        "loader_bottleneck",
        "fuel_efficiency_degradation",
        "ambiguous_stop",
        "ambiguous_mechanical_degradation",
    }


def test_manual_sabotage_profile_selection_is_varied_and_reproducible():
    first = causal_plan_for_sabotage("MECHANICAL_BREAKDOWN", "TRUCK", seed=5)
    replay = causal_plan_for_sabotage("MECHANICAL_BREAKDOWN", "TRUCK", seed=5)
    profiles = {
        causal_plan_for_sabotage("MECHANICAL_BREAKDOWN", "TRUCK", seed=seed)
        for seed in (1, 5, 8, 9)
    }

    assert first == replay
    assert len(profiles) == 4
    assert causal_plan_for_sabotage("MECHANICAL_BREAKDOWN", "LOADER", seed=5) is None


def _command_context(world, manager):
    return CommandContext(
        world=world,
        session=SimpleNamespace(),
        sim_now=NOW,
        open_states={},
        equip_id_by_code={code: truck.equipment_id for code, truck in world.trucks.items()},
        zone_id_by_code={},
        site_id=1,
        causal_scenarios=manager,
        causal_min_duration_min=1.0,
        causal_tick_sim_sec=30.0,
    )


@pytest.mark.parametrize(
    ("action", "expected_scenario", "final_flag"),
    [
        ("MECHANICAL_BREAKDOWN", "lubrication_degradation", "mechanical_hold"),
        ("COMMUNICATION_LOSS", "communication_degradation", "comm_lost"),
        ("FUEL_RATE_HIGH", "fuel_efficiency_degradation", None),
        ("STOP_UNDEFINED", "ambiguous_stop", "unexplained_hold"),
    ],
)
def test_existing_sabotage_command_starts_progression_before_final_condition(
    action,
    expected_scenario,
    final_flag,
):
    world = _world()
    manager = CausalScenarioManager()
    parameters = {"seed": 1}
    if action == "MECHANICAL_BREAKDOWN":
        parameters["profile"] = "lubrication"
    command = SimulationCommand.create(
        target_type="EQUIPMENT",
        target_id="TRK-001",
        action=action,
        parameters=parameters,
    )

    injection = _apply_command(_command_context(world, manager), command)
    truck = world.trucks["TRK-001"]
    run = next(iter(manager.active.values()))

    assert injection is not None
    assert run.scenario_id == expected_scenario
    assert run.progress == 0
    if final_flag:
        assert getattr(truck, final_flag) is False
    _complete(manager, world, run)
    if final_flag:
        assert getattr(truck, final_flag) is True
    else:
        assert truck.fuel_rate_factor > 2.0


def test_manual_sabotage_immediate_mode_retains_legacy_switch(monkeypatch):
    from simulator import apply_commands

    world = _world()
    manager = CausalScenarioManager()
    monkeypatch.setattr(apply_commands, "_persist_equipment_effects", lambda *_args: None)
    command = SimulationCommand.create(
        target_type="EQUIPMENT",
        target_id="TRK-001",
        action="MECHANICAL_BREAKDOWN",
        parameters={"immediate": True},
    )

    _apply_command(_command_context(world, manager), command)

    assert world.trucks["TRK-001"].mechanical_hold is True
    assert manager.active == {}


def test_undefined_stop_keeps_precursors_non_diagnostic():
    world = _world()
    manager = CausalScenarioManager()
    run = manager.activate(world, "ambiguous_stop", "TRK-001", NOW, seed=19)
    transitions = _complete(manager, world, run)

    assert world.trucks["TRK-001"].unexplained_hold
    assert transitions[-1].alert_type == "UNEXPLAINED_STOP"
    assert "cause non confirmée" in (transitions[-1].description or "")
    warning_sample = next(sample for sample in run.trace if sample.stage == CausalStage.WARNING)
    assert warning_sample.ts < run.incident_at


def test_manager_rejects_backwards_timestamps():
    world = _world()
    manager = CausalScenarioManager()
    run = manager.activate(world, "lubrication_degradation", "TRK-001", NOW)
    manager.step(world, NOW + timedelta(minutes=1))
    with pytest.raises(ValueError, match="backwards"):
        manager.step(world, NOW + timedelta(seconds=30))


def test_causal_scenario_developer_api_exposes_lifecycle_without_operational_coupling(
    monkeypatch,
):
    from app.api.routes import simulation

    class FakeService:
        def causal_scenario_status(self):
            return []

        def activate_causal_scenario(self, scenario_id, target_id, **kwargs):
            return {
                "run_id": "causal-test",
                "scenario_id": scenario_id,
                "target_id": target_id,
                "hidden_root_cause": "developer-only",
            }

        def stop_causal_scenario(self, run_id):
            return {"run_id": run_id, "target_id": "TRK-001"}

    monkeypatch.setattr(simulation, "get_simulation_service", lambda: FakeService())
    app = FastAPI()
    app.include_router(simulation.router, prefix="/api/simulation")
    client = TestClient(app)

    catalog = client.get("/api/simulation/causal-scenarios")
    started = client.post(
        "/api/simulation/causal-scenarios/lubrication_degradation/start",
        json={"target_id": "TRK-001", "seed": 42},
    )
    stopped = client.delete("/api/simulation/causal-scenarios/causal-test")

    assert catalog.status_code == 200 and len(catalog.json()["catalog"]) == len(SCENARIO_SPECS)
    assert started.status_code == 200 and started.json()["run"]["run_id"] == "causal-test"
    assert stopped.status_code == 200 and stopped.json()["ok"] is True
