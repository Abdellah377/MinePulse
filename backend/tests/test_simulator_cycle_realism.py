"""Zero-cost realism and lifecycle regression tests for haul-cycle simulation."""

from __future__ import annotations

import ast
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.db.database import SessionLocal
from app.db.enums import EquipmentState, EquipmentType
from app.db.models import Cycle, CycleStage, Equipment, Site, Trip
from app.db.models.telemetry import EquipmentState as EquipmentStateRow
from simulator.config import SimConfig
from simulator.cycle_dynamics import operating_conditions, sample_temporal_factor
from simulator.cycle_lifecycle import interrupt_active_simulation_cycles
from simulator.loaders import LoaderRuntime
from simulator.reset_cleanup import clear_simulation_run_data
from simulator.state_machine import TruckPhase, TruckRuntime


NOW = datetime(2026, 1, 29, 6, 0, tzinfo=timezone.utc)


def _cfg(*, speed: float = 30.0, seed: int = 42) -> SimConfig:
    cfg = SimConfig(random_seed=seed)
    cfg.speed = speed
    cfg.tick_seconds = 1.0
    return cfg


def _moving_ticks(
    distance_km: float,
    *,
    condition: float = 1.0,
    truck_factor: float = 1.0,
) -> int:
    truck = TruckRuntime(
        code="TRK-T",
        equipment_id=1,
        phase=TruckPhase.MOVING_LOADED,
        road_distance_km=distance_km,
        road_speed_limit=40.0,
        baseline_travel_factor=truck_factor,
        travel_condition_factor=condition,
        rng=random.Random(17),
    )
    cfg = _cfg()
    ticks = 0
    while truck.phase == TruckPhase.MOVING_LOADED and ticks < 500:
        truck.advance_phase(cfg)
        ticks += 1
    return ticks


def test_loading_duration_uses_simulated_seconds_not_fixed_animation_ticks():
    def elapsed_ticks(speed: float) -> int:
        cfg = _cfg(speed=speed)
        truck = TruckRuntime("TRK-001", 1, phase=TruckPhase.WAITING_LOADING)
        truck.phase_seconds_total = cfg.tick_seconds * cfg.speed
        truck.phase_seconds_left = cfg.tick_seconds * cfg.speed
        truck.advance_phase(cfg, loading_duration_seconds=180.0)
        ticks = 0
        while truck.phase == TruckPhase.LOADING:
            truck.advance_phase(cfg)
            ticks += 1
        return ticks

    ticks_30x = elapsed_ticks(30.0)
    ticks_60x = elapsed_ticks(60.0)
    assert ticks_30x * 30 == pytest.approx(180, abs=30)
    assert ticks_60x * 60 == pytest.approx(180, abs=60)


def test_loader_queue_is_fifo_and_allows_only_one_active_truck():
    loader = LoaderRuntime("EXC-001", 100)
    assert loader.request_service("TRK-001") is True
    assert loader.request_service("TRK-002") is False
    assert loader.request_service("TRK-003") is False
    assert loader.active_truck_code == "TRK-001"
    assert loader.waiting_queue == ["TRK-002", "TRK-003"]

    loader.release_service("TRK-001")
    assert loader.request_service("TRK-002") is True
    assert loader.active_truck_code == "TRK-002"


def test_seeded_loader_service_varies_within_loader_and_is_reproducible():
    cfg = _cfg().cycle_dynamics

    def samples(seed: int, factor: float) -> list[float]:
        loader = LoaderRuntime(
            "EXC-001",
            100,
            baseline_service_factor=factor,
            rng=random.Random(seed),
        )
        return [loader.sample_loading_seconds(cfg) for _ in range(30)]

    first = samples(9, 1.0)
    assert first == samples(9, 1.0)
    assert first != samples(10, 1.0)
    assert len({round(value, 2) for value in first}) > 20
    assert sum(samples(9, 1.07)) / 30 > sum(samples(9, 0.93)) / 30


def test_loader_degradation_lengthens_observable_loading_stage():
    cfg = _cfg(speed=30.0)

    def elapsed_ticks(rate: float) -> int:
        truck = TruckRuntime("TRK-T", 1, phase=TruckPhase.WAITING_LOADING)
        truck.phase_seconds_total = cfg.tick_seconds * cfg.speed
        truck.phase_seconds_left = cfg.tick_seconds * cfg.speed
        truck.advance_phase(cfg, loading_duration_seconds=210.0)
        ticks = 0
        while truck.phase == TruckPhase.LOADING and ticks < 100:
            truck.advance_phase(cfg, loading_rate=rate)
            ticks += 1
        return ticks

    assert elapsed_ticks(0.58) > elapsed_ticks(1.0)


def test_route_distance_and_observed_speed_conditions_drive_travel_time():
    short = _moving_ticks(4.0)
    long = _moving_ticks(8.0)
    degraded = _moving_ticks(4.0, condition=0.58)
    assert long > short
    assert degraded > short
    assert long < short * 3  # noisy relationship, not a direct duration formula


def test_truck_performance_has_modest_not_target_level_influence():
    faster = _moving_ticks(5.6, truck_factor=1.05)
    slower = _moving_ticks(5.6, truck_factor=0.92)
    assert slower > faster
    assert slower < faster * 1.5


def test_operating_periods_are_seeded_diverse_and_mostly_bounded():
    replay = operating_conditions(
        seed=42, sim_now=NOW, asset_token="road:RD-1", period_minutes=60
    )
    assert replay == operating_conditions(
        seed=42, sim_now=NOW, asset_token="road:RD-1", period_minutes=60
    )
    assert replay != operating_conditions(
        seed=43, sim_now=NOW, asset_token="road:RD-1", period_minutes=60
    )
    later = operating_conditions(
        seed=42,
        sim_now=NOW + timedelta(hours=1),
        asset_token="road:RD-1",
        period_minutes=60,
    )
    assert later != replay
    assert 0.5 <= replay.travel_factor <= 1.05
    assert 0.5 <= replay.loader_rate_factor <= 1.05


def test_temporal_variability_is_mostly_normal_with_a_rare_degraded_tail():
    rng = random.Random(42)
    factors = [sample_temporal_factor(rng) for _ in range(1_000)]
    normal = sum(value >= 0.91 for value in factors)
    strong_degradation = sum(value < 0.76 for value in factors)
    assert normal > 700
    assert 10 < strong_degradation < 100


def test_production_packages_do_not_import_simulator_internals():
    backend = Path(__file__).resolve().parents[1]
    for package in ("app/ml", "app/ai", "app/monitoring"):
        for path in (backend / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(not item.name.startswith("simulator") for item in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith("simulator")


@pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="cycle lifecycle persistence verification requires --integration and PostgreSQL",
)
def test_engine_restart_interrupts_only_scoped_active_cycles():
    suffix = uuid4().hex[:10]
    sim_site = Site(
        code=f"CYCLE-SIM-{suffix}",
        name="Cycle simulator test",
        timezone="UTC",
        active=True,
        created_at=NOW,
    )
    real_site = Site(
        code=f"CYCLE-REAL-{suffix}",
        name="Cycle real test",
        timezone="UTC",
        active=True,
        created_at=NOW,
    )
    with SessionLocal() as session:
        session.add_all([sim_site, real_site])
        session.flush()
        sim_truck = Equipment(
            site_id=sim_site.site_id,
            code="TRK-SIM",
            type=EquipmentType.HAUL_TRUCK,
            current_state=EquipmentState.MOVING_EMPTY,
            active=True,
            metadata_={"simulated": True},
        )
        real_truck = Equipment(
            site_id=real_site.site_id,
            code="TRK-REAL",
            type=EquipmentType.HAUL_TRUCK,
            current_state=EquipmentState.MOVING_EMPTY,
            active=True,
        )
        session.add(sim_truck)
        session.flush()
        session.add(real_truck)
        session.flush()
        sim_cycle = Cycle(truck_id=sim_truck.equipment_id, started_at=NOW, status="ACTIVE")
        real_cycle = Cycle(truck_id=real_truck.equipment_id, started_at=NOW, status="ACTIVE")
        session.add_all([sim_cycle, real_cycle])
        session.flush()
        stage = CycleStage(
            cycle_id=sim_cycle.cycle_id,
            stage=EquipmentState.MOVING_EMPTY,
            start_time=NOW,
            sequence_no=1,
        )
        trip = Trip(
            truck_id=sim_truck.equipment_id,
            cycle_id=sim_cycle.cycle_id,
            start_time=NOW,
            status="ACTIVE",
        )
        state = EquipmentStateRow(
            equipment_id=sim_truck.equipment_id,
            state=EquipmentState.MOVING_EMPTY,
            start_time=NOW,
        )
        session.add_all([stage, trip, state])
        session.commit()

        try:
            counts = interrupt_active_simulation_cycles(
                session,
                site_id=sim_site.site_id,
                interrupted_at=NOW + timedelta(minutes=12),
                reason="TEST_RESTART",
            )
            session.commit()
            session.refresh(sim_cycle)
            session.refresh(real_cycle)
            session.refresh(stage)
            session.refresh(trip)
            assert counts == {
                "cycles": 1,
                "cycle_stages": 1,
                "trips": 1,
                "equipment_states": 1,
            }
            assert sim_cycle.status == "INTERRUPTED"
            assert sim_cycle.total_duration_sec is None
            assert stage.duration_sec == 12 * 60
            assert trip.status == "INTERRUPTED"
            assert real_cycle.status == "ACTIVE"
        finally:
            session.execute(delete(Site).where(Site.site_id.in_([sim_site.site_id, real_site.site_id])))
            session.commit()


@pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="reset cycle cleanup verification requires --integration and PostgreSQL",
)
def test_reset_deletes_simulation_active_cycles_but_preserves_other_sites():
    suffix = uuid4().hex[:10]
    sim_site = Site(
        code=f"RESET-CYCLE-SIM-{suffix}",
        name="Reset cycle simulator test",
        timezone="UTC",
        active=True,
        created_at=NOW,
    )
    real_site = Site(
        code=f"RESET-CYCLE-REAL-{suffix}",
        name="Reset cycle real test",
        timezone="UTC",
        active=True,
        created_at=NOW,
    )
    with SessionLocal() as session:
        session.add_all([sim_site, real_site])
        session.flush()
        sim_truck = Equipment(
            site_id=sim_site.site_id,
            code="TRK-SIM-RESET",
            type=EquipmentType.HAUL_TRUCK,
            current_state=EquipmentState.MOVING_EMPTY,
            active=True,
        )
        real_truck = Equipment(
            site_id=real_site.site_id,
            code="TRK-REAL-RESET",
            type=EquipmentType.HAUL_TRUCK,
            current_state=EquipmentState.MOVING_EMPTY,
            active=True,
        )
        session.add(sim_truck)
        session.flush()
        session.add(real_truck)
        session.flush()
        sim_cycle = Cycle(truck_id=sim_truck.equipment_id, started_at=NOW, status="ACTIVE")
        real_cycle = Cycle(truck_id=real_truck.equipment_id, started_at=NOW, status="ACTIVE")
        session.add_all([sim_cycle, real_cycle])
        session.commit()
        sim_cycle_id = sim_cycle.cycle_id
        real_cycle_id = real_cycle.cycle_id

        try:
            counts = clear_simulation_run_data(session, site_code=sim_site.code)
            session.commit()
            assert counts["cycles"] == 1
            assert session.get(Cycle, sim_cycle_id) is None
            assert session.get(Cycle, real_cycle_id) is not None
        finally:
            session.execute(delete(Site).where(Site.site_id.in_([sim_site.site_id, real_site.site_id])))
            session.commit()
