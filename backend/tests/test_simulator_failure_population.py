"""Zero-cost tests for seeded simulator-only mechanical incident populations."""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.database import SessionLocal
from app.db.enums import AlertSeverity, EquipmentState, EquipmentType
from app.db.models import Cycle, CycleStage, DowntimeEvent, Equipment, MaintenanceEvent, Site, Trip
from app.db.models.telemetry import EquipmentState as EquipmentStateRow
from simulator.cli import build_parser, cmd_generate_cycles
from simulator.config import SimConfig
from app.oem.thresholds import classify_value
from simulator.causal_scenarios import CausalScenarioManager
from simulator.causal_scenarios import CausalStage, ObservableTransition
from simulator.failure_population import FailurePopulationConfig, FailurePopulationManager
from simulator.generators.telemetry import build_telemetry
from simulator.state_machine import TruckPhase, TruckRuntime
from simulator.transition_service import truck_db_state


NOW = datetime(2026, 1, 29, 6, 0, tzinfo=timezone.utc)


def test_generate_cycles_default_does_not_enable_failure_population():
    args = build_parser().parse_args(["generate-cycles"])
    assert args.with_failures is False
    assert SimConfig(random_seed=42).failure_population.enabled is False


def test_generate_cycles_with_failures_flag_enables_existing_manager():
    args = build_parser().parse_args(
        ["generate-cycles", "--target-cycles", "1000", "--seed", "42", "--sim-speed", "60", "--with-failures"]
    )
    assert args.with_failures is True
    cfg = SimConfig(random_seed=args.seed)
    cfg.failure_population = FailurePopulationConfig(enabled=args.with_failures)
    manager = FailurePopulationManager(cfg.failure_population, seed=cfg.random_seed)
    assert manager.config.enabled is True
    assert type(manager) is FailurePopulationManager


def test_generate_cycles_command_uses_existing_population_not_parallel_logic():
    source = inspect.getsource(cmd_generate_cycles)
    assert "FailurePopulationConfig(enabled=with_failures)" in source
    assert "engine.failure_population" in source
    assert "developer_summary" in source
    assert "stop_scheduling" in source
    assert '"failures_enabled": with_failures' in source
    assert "class FailurePopulationManager" not in source


def test_disabled_failure_population_starts_no_incidents():
    world = _world()
    causal = CausalScenarioManager()
    population = FailurePopulationManager(FailurePopulationConfig(), seed=42)
    assert population.config.enabled is False
    for minute in range(180):
        population.advance(world, causal, NOW + timedelta(minutes=minute))
    assert population.history == []
    assert population.active == {}
    assert causal.active == {}


def test_generate_cycles_same_seed_with_failures_is_reproducible():
    cfg = SimConfig(random_seed=42)
    cfg.failure_population = FailurePopulationConfig(enabled=True)

    def run() -> list[tuple]:
        world = _world()
        causal = CausalScenarioManager()
        population = FailurePopulationManager(cfg.failure_population, seed=cfg.random_seed)
        for minute in range(240):
            population.advance(world, causal, NOW + timedelta(minutes=minute))
        return _stable_history(population)

    assert run() == run()
    cfg_other = SimConfig(random_seed=43)
    cfg_other.failure_population = FailurePopulationConfig(enabled=True)
    world = _world()
    causal = CausalScenarioManager()
    other = FailurePopulationManager(cfg_other.failure_population, seed=cfg_other.random_seed)
    for minute in range(240):
        other.advance(world, causal, NOW + timedelta(minutes=minute))
    assert _stable_history(other) != run()


def test_persisted_failure_records_omit_hidden_simulator_truth():
    from simulator.failure_lifecycle import start_mechanical_incident

    maintenance_source = inspect.getsource(start_mechanical_incident)
    assert "hidden_root_cause" not in maintenance_source
    assert "profile_id" not in maintenance_source
    assert "scenario_id" not in maintenance_source
    assert "performance_factor" not in maintenance_source
    assert '"source": "SIMULATOR_FAILURE"' in maintenance_source


def _world(count: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        trucks={
            f"TRK-{index:03d}": TruckRuntime(
                code=f"TRK-{index:03d}",
                equipment_id=index,
                phase=TruckPhase.MOVING_EMPTY,
            )
            for index in range(1, count + 1)
        },
        loaders={},
    )


def _run_population(seed: int, *, minutes: int = 720):
    world = _world()
    causal = CausalScenarioManager()
    population = FailurePopulationManager(
        FailurePopulationConfig(
            enabled=True,
            warmup_min=5,
            spacing_min=12,
            spacing_max=18,
            degradation_min=70,
            degradation_max=85,
            repair_min=10,
            repair_max=20,
            max_concurrent=6,
        ),
        seed=seed,
    )
    for minute in range(minutes + 1):
        if minute == minutes - 120:
            population.stop_scheduling()
        population.advance(world, causal, NOW + timedelta(minutes=minute))
    return world, causal, population


def _stable_history(population: FailurePopulationManager) -> list[tuple]:
    return [
        (
            incident.target_id,
            incident.profile_id,
            round((incident.started_at - NOW).total_seconds() / 60),
            round(incident.degradation_minutes, 2),
            round(incident.repair_minutes, 2),
        )
        for incident in population.history
    ]


def test_failure_population_is_reproducible_and_seed_changes_schedule():
    _, _, first = _run_population(42)
    _, _, replay = _run_population(42)
    _, _, different = _run_population(43)

    assert _stable_history(first) == _stable_history(replay)
    assert _stable_history(first) != _stable_history(different)


def test_failure_population_balances_independent_incidents_across_trucks():
    _, _, population = _run_population(42)
    counts = Counter(item.target_id for item in population.history)

    assert len(population.history) >= 20
    assert len(counts) >= 15
    assert max(counts.values()) - min(counts.values()) <= 1
    assert len({item.profile_id for item in population.history}) >= 3


def test_failure_population_provides_long_precursors_and_clean_recovery():
    world, causal, population = _run_population(17)
    completed = [item for item in population.history if item.recovered_at is not None]

    assert completed
    assert all(item.incident_at is not None for item in completed)
    assert all(
        (item.incident_at - item.started_at) >= timedelta(minutes=60)
        for item in completed
        if item.incident_at is not None
    )
    assert all(item.recovered_at > item.incident_at for item in completed if item.incident_at)
    assert not any(truck.mechanical_hold for truck in world.trucks.values())
    assert causal.active == {}


def test_mechanical_profiles_create_distinct_observable_precursors():
    world = _world(3)
    manager = CausalScenarioManager()
    runs = {
        "lubrication": manager.activate(
            world, "lubrication_degradation", "TRK-001", NOW, duration_min=80, seed=10
        ),
        "cooling": manager.activate(
            world, "cooling_degradation", "TRK-002", NOW, duration_min=80, seed=11
        ),
        "electrical": manager.activate(
            world, "electrical_degradation", "TRK-003", NOW, duration_min=80, seed=12
        ),
    }
    at = NOW + timedelta(minutes=64)
    for _ in range(8):
        manager.step(world, at)
        readings = {code: build_telemetry(truck) for code, truck in world.trucks.items()}

    lubrication = readings["TRK-001"]
    cooling = readings["TRK-002"]
    electrical = readings["TRK-003"]
    assert lubrication["oil_pressure_kpa"] < cooling["oil_pressure_kpa"]
    assert cooling["coolant_temp_c"] > electrical["coolant_temp_c"]
    assert electrical["battery_voltage"] < lubrication["battery_voltage"]


def test_healthy_operation_can_overlap_mild_thermal_warning_range():
    truck = TruckRuntime("TRK-HEALTHY", 1, phase=TruckPhase.MOVING_LOADED)
    flagged = 0
    samples = 60
    for index in range(samples):
        truck.phase = (
            TruckPhase.MOVING_LOADED if index % 20 < 8 else TruckPhase.MOVING_EMPTY
        )
        row = build_telemetry(truck)
        flagged += classify_value("engine_temp_c", float(row["engine_temp_c"])) is not None

    assert 0 < flagged < samples
    assert not truck.mechanical_hold


def test_ambiguous_mechanical_profile_is_not_a_single_oem_threshold_rule():
    world = _world(1)
    truck = world.trucks["TRK-001"]
    truck.phase = TruckPhase.MOVING_LOADED
    truck.payload_t = 175.0
    manager = CausalScenarioManager()
    manager.activate(
        world,
        "ambiguous_mechanical_degradation",
        truck.code,
        NOW,
        duration_min=80,
        seed=44,
    )

    rows = []
    for minute in range(1, 75):
        manager.step(world, NOW + timedelta(minutes=minute))
        rows.append(build_telemetry(truck))

    last = rows[-1]
    warning_keys = {
        key
        for key in (
            "engine_temp_c",
            "coolant_temp_c",
            "oil_pressure_kpa",
            "battery_voltage",
            "fuel_rate_lph",
            "communication_quality",
        )
        if classify_value(key, float(last[key])) is not None
    }
    assert warning_keys == set()
    assert truck.mechanical_hold


def test_tyre_safety_stop_persists_as_maintenance_not_mechanical_failure():
    world = _world(1)
    truck = world.trucks["TRK-001"]
    manager = CausalScenarioManager()
    run = manager.activate(world, "tyre_degradation", truck.code, NOW, seed=31)

    manager.step(world, NOW + timedelta(seconds=run.duration_sec))

    assert truck.in_maintenance
    assert truck_db_state(truck) == EquipmentState.MAINTENANCE


def test_tyre_safety_stop_interrupts_open_work_and_opens_failure_lifecycle(monkeypatch):
    from simulator import engine as engine_module
    from simulator.engine import SimulationEngine

    truck = TruckRuntime("TRK-001", 1, phase=TruckPhase.MOVING_LOADED)
    truck.in_maintenance = True
    world = SimpleNamespace(trucks={truck.code: truck})
    interrupted = []
    transitioned = []
    lifecycle = []
    engine = object.__new__(SimulationEngine)
    engine.equip_id_by_code = {truck.code: truck.equipment_id}
    engine.world = world
    engine.failure_population = SimpleNamespace(active={})
    engine.open_failure_records = {}
    engine.session = SimpleNamespace(add=lambda *_args: None)
    engine._interrupt_truck_work = lambda item, **kwargs: interrupted.append((item, kwargs))
    engine._transition_truck = lambda item, **kwargs: transitioned.append((item, kwargs))
    monkeypatch.setattr(engine_module, "emit_system_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(engine_module, "emit_fms_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        engine_module,
        "start_mechanical_incident",
        lambda *args, **kwargs: lifecycle.append(kwargs) or "records",
    )
    transition = ObservableTransition(
        run_id="tyre-run",
        target_id=truck.code,
        occurred_at=NOW,
        stage=CausalStage.INCIDENT,
        event_kind="SAFETY_STOP",
        alert_type="EQUIPMENT_SAFETY_STOP",
        severity="CRITICAL",
        maintenance_required=True,
    )

    engine._persist_causal_transitions([transition])

    assert interrupted == [(truck, {"interrupted_at": NOW})]
    assert transitioned == [(truck, {"sim_now": NOW})]
    assert lifecycle == [
        {
            "equipment_id": 1,
            "started_at": NOW,
            "expected_recovery_at": NOW + timedelta(minutes=30),
            "severity": AlertSeverity.CRITICAL,
        }
    ]
    assert engine.open_failure_records == {"tyre-run": "records"}


def test_failure_population_hidden_truth_stays_out_of_production_packages():
    backend = Path(__file__).resolve().parents[1]
    for package in ("app/ml", "app/ai", "app/monitoring"):
        for path in (backend / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(not item.name.startswith("simulator") for item in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith("simulator")


@pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="mechanical lifecycle persistence requires PostgreSQL",
)
def test_mechanical_incident_persistence_recovers_without_hidden_truth():
    from simulator.failure_lifecycle import recover_mechanical_incident, start_mechanical_incident

    suffix = uuid4().hex[:10]
    site = Site(
        code=f"FAILURE-LIFECYCLE-{suffix}",
        name="Failure lifecycle test",
        timezone="UTC",
        active=True,
        created_at=NOW,
    )
    with SessionLocal() as session:
        session.add(site)
        session.flush()
        truck = Equipment(
            site_id=site.site_id,
            code=f"TRK-FAIL-{suffix}",
            type=EquipmentType.HAUL_TRUCK,
            current_state=EquipmentState.STOPPED_MECHANICAL,
            active=True,
        )
        session.add(truck)
        session.flush()
        try:
            records = start_mechanical_incident(
                session,
                equipment_id=truck.equipment_id,
                started_at=NOW,
                expected_recovery_at=NOW + timedelta(minutes=35),
                severity=AlertSeverity.CRITICAL,
            )
            session.flush()
            maintenance = records.maintenance(session)
            downtime = records.downtime(session)
            assert maintenance.status == "OPEN"
            assert maintenance.component is None
            assert downtime.end_time is None
            assert downtime.category == "MECHANICAL"
            assert "scenario" not in str(maintenance.metadata_).casefold()
            assert "profile" not in str(downtime.metadata_).casefold()

            recover_mechanical_incident(
                session,
                records,
                recovered_at=NOW + timedelta(minutes=35),
            )
            session.flush()
            assert maintenance.status == "CLOSED"
            assert maintenance.actual_end_time == NOW + timedelta(minutes=35)
            assert downtime.end_time == NOW + timedelta(minutes=35)
        finally:
            session.execute(delete(Site).where(Site.site_id == site.site_id))
            session.commit()


@pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="cycle interruption persistence requires PostgreSQL",
)
def test_failure_interrupts_active_cycle_trip_and_stage_without_ml_target():
    from simulator.cycle_lifecycle import interrupt_active_truck_work

    suffix = uuid4().hex[:10]
    site = Site(
        code=f"FAILURE-CYCLE-{suffix}",
        name="Failure cycle test",
        timezone="UTC",
        active=True,
        created_at=NOW,
    )
    with SessionLocal() as session:
        session.add(site)
        session.flush()
        truck = Equipment(
            site_id=site.site_id,
            code=f"TRK-CYCLE-{suffix}",
            type=EquipmentType.HAUL_TRUCK,
            current_state=EquipmentState.MOVING_LOADED,
            active=True,
        )
        session.add(truck)
        session.flush()
        cycle = Cycle(truck_id=truck.equipment_id, started_at=NOW, status="ACTIVE")
        session.add(cycle)
        session.flush()
        stage = CycleStage(
            cycle_id=cycle.cycle_id,
            stage=EquipmentState.MOVING_LOADED,
            start_time=NOW,
            sequence_no=4,
        )
        trip = Trip(
            truck_id=truck.equipment_id,
            cycle_id=cycle.cycle_id,
            start_time=NOW,
            status="ACTIVE",
        )
        session.add_all([stage, trip])
        session.flush()
        try:
            interrupt_active_truck_work(
                session,
                cycle_id=cycle.cycle_id,
                stage_id=stage.cycle_stage_id,
                trip_id=trip.trip_id,
                interrupted_at=NOW + timedelta(minutes=22),
                reason="MECHANICAL_STOP",
            )
            session.flush()
            assert cycle.status == "INTERRUPTED"
            assert cycle.total_duration_sec is None
            assert stage.duration_sec == 22 * 60
            assert trip.status == "INTERRUPTED"
        finally:
            session.execute(delete(Site).where(Site.site_id == site.site_id))
            session.commit()


@pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="end-to-end failure population persistence requires PostgreSQL",
)
def test_engine_persists_stop_downtime_recovery_and_interrupted_cycle():
    from simulator.engine import SimulationEngine

    cfg = SimConfig(random_seed=91)
    cfg.speed = 60.0
    cfg.persistence_sample_every_ticks = 1
    cfg.failure_population = FailurePopulationConfig(
        enabled=True,
        warmup_min=0,
        spacing_min=999,
        spacing_max=999,
        degradation_min=2,
        degradation_max=2,
        repair_min=2,
        repair_max=2,
        max_concurrent=1,
        profiles=("lubrication_degradation",),
    )
    with SessionLocal() as session:
        engine = SimulationEngine(session, cfg=cfg)
        engine.reset()
        engine.start()
        try:
            for _ in range(8):
                engine.tick()
            engine.pause()
            equipment_ids = select(Equipment.equipment_id).where(
                Equipment.site_id == engine.site_id
            )
            stopped = list(
                session.scalars(
                    select(EquipmentStateRow).where(
                        EquipmentStateRow.equipment_id.in_(equipment_ids),
                        EquipmentStateRow.state == EquipmentState.STOPPED_MECHANICAL,
                    )
                ).all()
            )
            assert len(stopped) == 1
            assert stopped[0].end_time is not None
            downtime = session.scalar(
                select(DowntimeEvent).where(DowntimeEvent.equipment_id.in_(equipment_ids))
            )
            maintenance = session.scalar(
                select(MaintenanceEvent).where(MaintenanceEvent.equipment_id.in_(equipment_ids))
            )
            assert downtime is not None and downtime.end_time is not None
            assert stopped[0].start_time == downtime.start_time
            assert stopped[0].end_time == downtime.end_time
            assert maintenance is not None and maintenance.status == "CLOSED"
            assert session.scalar(
                select(func.count()).select_from(Cycle).where(
                    Cycle.truck_id.in_(equipment_ids), Cycle.status == "INTERRUPTED"
                )
            ) >= 1
        finally:
            engine.reset()
