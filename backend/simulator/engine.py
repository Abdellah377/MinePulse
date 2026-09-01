"""Main simulation engine — ticks trucks and persists to PostgreSQL."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.enums import AlertSeverity, EquipmentState, EquipmentType
from app.db.models import (
    Cycle,
    CycleStage,
    Equipment,
    EquipmentAssignment,
    EquipmentPosition,
    EquipmentState as EquipmentStateRow,
    EquipmentTelemetry,
    FuelEvent,
    MaintenanceEvent,
    Material,
    Operator,
    Site,
    Trip,
    TyreTelemetry,
)
from app.oem.schema import ensure_oem_schema
from simulator.apply_commands import CommandContext, process_equipment_commands, process_pending_commands
from simulator.causal_scenarios import CausalScenarioManager, ObservableTransition, SCENARIO_SPECS
from simulator.clock import SimClock, get_sim_logger
from simulator.commands import clear_commands, clear_event_log, load_all_commands
from simulator.config import SimConfig
from simulator.control import COMMANDS_PATH, read_control, write_control, write_heartbeat
from simulator.generators.events import emit_fms_alert, emit_system_event
from simulator.generators.production import record_dump_production
from simulator.generators.telemetry import build_telemetry
from simulator.generators.tyres import tyre_rows
from simulator.failure_lifecycle import (
    PersistedFailureRecords,
    reconcile_open_simulation_failures,
    recover_mechanical_incident,
    start_mechanical_incident,
)
from simulator.failure_population import FailurePopulationManager, PopulationIncident
from simulator.geometry import (
    find_road,
    interpolate_linestring,
    load_roads,
    load_zones,
    point_wkt,
    resolve_zone_id,
)
from simulator.loaders import LoaderRuntime
from simulator.queues import RoadRuntime, ZoneRuntime
from simulator.scenarios import apply_scenarios
from simulator.state_machine import (
    CYCLE_PHASES,
    PHASE_TO_DB,
    STAGE_SEQUENCE,
    TruckPhase,
    TruckRuntime,
)
from simulator.world_model import SimulationWorld
from simulator.world import stable_seed

from simulator.transition_service import (
    OpenStateRef,
    loader_db_state,
    transition_loader,
    transition_truck,
)

log = get_sim_logger()


class SimulationEngine:
    def __init__(self, session: Session, cfg: SimConfig | None = None) -> None:
        self.session = session
        self.cfg = cfg or SimConfig()
        self.world = SimulationWorld(self.cfg)
        self.causal_scenarios = CausalScenarioManager()
        self.failure_population = FailurePopulationManager(
            self.cfg.failure_population,
            seed=self.cfg.random_seed,
        )
        control = read_control()
        sim_now = datetime.fromisoformat(control["sim_now"])
        if sim_now.tzinfo is None:
            sim_now = sim_now.replace(tzinfo=timezone.utc)
        initial_speed = self.cfg.speed if cfg is not None else control.get("speed", self.cfg.speed)
        self.clock = SimClock(float(initial_speed), self.cfg.tick_seconds, sim_now)
        self.clock.status = control.get("status", "STOPPED")
        self.cfg.scenario = control.get("scenario", "normal")
        self.world.mode = control.get("mode", "MANUAL")
        self.site_id: int | None = None
        self.shift_id: int | None = None
        self.material_id: int | None = None
        self.zone_id_by_code: dict[str, int] = {}
        self.zone_code_by_id: dict[int, str] = {}
        self.equip_id_by_code: dict[str, int] = {}
        self.zones_geom = {}
        self.roads_geom = {}
        self.open_states: dict[str, OpenStateRef] = {}
        self.open_cycles: dict[str, int] = {}
        self.open_cycle_stages: dict[str, int] = {}
        self.open_trips: dict[str, int] = {}
        self.open_failure_records: dict[str, PersistedFailureRecords] = {}
        self._last_queue_log: dict[str, int] = {}
        self._tick_count = 0
        self.completed_cycle_count = 0
        self.startup_interrupted_cycles = 0
        self._pending_positions: list[dict] = []
        self._pending_telemetry: list[dict] = []
        self._pending_tyres: list[dict] = []
        self._equipment_by_id: dict[int, Equipment] = {}
        self._loader_persisted_state: dict[str, EquipmentState] = {}
        self._commands_mtime: float | None = None
        self._commands_cache: list = []
        self._shift_spec_key: tuple | None = None
        self._boot()

    def _boot(self) -> None:
        ensure_oem_schema(self.session)
        site = self.session.scalar(select(Site).where(Site.code == "MP-SIM-01"))
        if not site:
            raise RuntimeError("Site MP-SIM-01 not seeded. Run: python -m simulator seed")
        self.site_id = site.site_id
        from simulator.cycle_lifecycle import interrupt_active_simulation_cycles

        lifecycle_counts = interrupt_active_simulation_cycles(
            self.session,
            site_id=site.site_id,
            interrupted_at=self.clock.sim_now,
            reason="SIMULATOR_ENGINE_RESTART",
        )
        self.startup_interrupted_cycles += lifecycle_counts["cycles"]
        reconcile_open_simulation_failures(
            self.session,
            site_id=site.site_id,
            reconciled_at=self.clock.sim_now,
        )
        material = self.session.scalar(select(Material).where(Material.code == "PHOS_SIM"))
        self.material_id = material.material_id if material else None
        from simulator.shifts import ensure_simulation_shift

        shift = ensure_simulation_shift(
            self.session,
            site_id=site.site_id,
            material_id=self.material_id,
            sim_now=self.clock.sim_now,
        )
        self.shift_id = shift.shift_id

        self.zones_geom = load_zones(self.session, site.site_id)
        self.zone_id_by_code = {c: z.zone_id for c, z in self.zones_geom.items()}
        self.zone_code_by_id = {z.zone_id: c for c, z in self.zones_geom.items()}
        self.roads_geom = load_roads(self.session, site.site_id, self.zone_code_by_id)

        all_equip = self.session.scalars(
            select(Equipment)
            .where(Equipment.site_id == site.site_id)
            .order_by(Equipment.equipment_id, Equipment.code)
        ).all()
        self.equip_id_by_code = {e.code: e.equipment_id for e in all_equip}
        self._equipment_by_id = {e.equipment_id: e for e in all_equip}
        self._loader_persisted_state = {
            e.code: e.current_state
            for e in all_equip
            if e.type in (EquipmentType.EXCAVATOR, EquipmentType.LOADER)
        }
        trucks = [(e.equipment_id, e.code) for e in all_equip if e.type == EquipmentType.HAUL_TRUCK]
        centroids = {c: z.centroid for c, z in self.zones_geom.items()}
        self.world.load_trucks(trucks, self.cfg.random_seed, centroids)
        self._hydrate_truck_telemetry()
        self._boot_world_runtime(all_equip)
        for truck in self.world.trucks.values():
            self._bind_road(truck)
        self._ensure_assignments()

    def _hydrate_truck_telemetry(self) -> None:
        """Continue persisted sensor values across simulator process restarts."""
        for truck in self.world.trucks.values():
            latest = self.session.scalar(
                select(EquipmentTelemetry)
                .where(EquipmentTelemetry.equipment_id == truck.equipment_id)
                .order_by(EquipmentTelemetry.ts.desc())
                .limit(1)
            )
            if latest is None:
                continue
            mappings = {
                "fuel_pct": "fuel_level_pct",
                "engine_temp_c": "engine_temp_c",
                "coolant_temp_c": "coolant_temp_c",
                "oil_pressure_kpa": "oil_pressure_kpa",
                "battery_voltage": "battery_voltage",
                "communication_quality": "communication_quality",
                "engine_hours": "engine_hours",
                "odometer_km": "odometer_km",
            }
            for runtime_name, column_name in mappings.items():
                value = getattr(latest, column_name, None)
                if value is not None:
                    setattr(truck, runtime_name, float(value))

    def _boot_world_runtime(self, all_equip) -> None:
        # Zones
        for code, zg in self.zones_geom.items():
            cap = 3
            # Prefer DB capacity if available via zone_id lookup
            from app.db.models import Zone as ZoneModel

            zrow = self.session.get(ZoneModel, zg.zone_id)
            if zrow and zrow.capacity:
                cap = int(zrow.capacity)
            self.world.zones[code] = ZoneRuntime(
                code=code,
                zone_id=zg.zone_id,
                name=zrow.name if zrow else code,
                zone_type=zrow.type.value if zrow and hasattr(zrow.type, "value") else "OTHER",
                base_capacity=cap,
                capacity=cap,
            )
        # Roads
        for key, rg in self.roads_geom.items():
            if "->" in key and key != rg.code:
                continue  # skip alias keys
            self.world.roads[rg.code] = RoadRuntime(
                code=rg.code,
                road_id=rg.road_id,
                from_zone=rg.from_zone_code,
                to_zone=rg.to_zone_code,
                distance_km=rg.distance_km,
                base_speed_limit=rg.speed_limit_kmh,
                speed_limit=rg.speed_limit_kmh,
                grade_pct=rg.grade_pct,
                quality_score=rg.quality_score,
            )
        # Loaders / excavators
        for e in all_equip:
            if e.type not in (EquipmentType.EXCAVATOR, EquipmentType.LOADER):
                continue
            zone = "BANC_B" if "002" in e.code or "003" in e.code else "BANC_A"
            if e.code.endswith("001"):
                zone = "BANC_A"
            elif e.code.endswith("002"):
                zone = "BANC_B"
            loader_rng_seed = stable_seed(self.cfg.random_seed, e.equipment_id, e.code)
            loader_rng = random.Random(loader_rng_seed)
            self.world.loaders[e.code] = LoaderRuntime(
                code=e.code,
                equipment_id=e.equipment_id,
                zone_code=zone,
                baseline_service_factor=loader_rng.uniform(
                    self.cfg.cycle_dynamics.loader_factor_min,
                    self.cfg.cycle_dynamics.loader_factor_max,
                ),
                rng=loader_rng,
            )

    def _sync_control_from_disk(self) -> None:
        """Re-read status/speed/mode/scenario so API changes apply live."""
        control = read_control()
        status = control.get("status", self.clock.status)
        if status in ("RUNNING", "PAUSED", "STOPPED"):
            self.clock.status = status
        try:
            speed = float(control.get("speed", self.clock.speed))
            if speed > 0:
                self.clock.speed = speed
                self.cfg.speed = speed
        except (TypeError, ValueError):
            pass
        self.world.mode = control.get("mode", self.world.mode)
        self.cfg.scenario = control.get("scenario", self.cfg.scenario)

    def _bind_road(self, truck: TruckRuntime) -> None:
        if truck.phase == TruckPhase.MOVING_LOADED:
            fr, to = truck.origin_zone_code, truck.dest_zone_code
        elif truck.phase == TruckPhase.MOVING_EMPTY:
            fr, to = truck.dest_zone_code, truck.origin_zone_code
        elif truck.phase == TruckPhase.REFUELING:
            fr, to = truck.origin_zone_code, "FUEL"
        else:
            fr, to = truck.origin_zone_code, truck.dest_zone_code
        road, reverse = find_road(self.roads_geom, fr, to)
        if road is None:
            # Fallback: any road from origin
            road, reverse = find_road(self.roads_geom, truck.origin_zone_code, "CRUSHER")
        if road:
            truck.active_road_code = road.code
            truck.road_reverse = reverse
            truck.road_distance_km = road.distance_km
            truck.road_grade_pct = road.grade_pct
            truck.road_quality_score = road.quality_score
            # Prefer live road runtime limits (injections)
            rr = self.world.roads.get(road.code)
            if rr and not rr.closed:
                truck.road_speed_limit = (
                    rr.speed_limit * rr.slow_traffic_factor * rr.operating_factor
                )
            elif rr and rr.closed:
                # Find alternative to crusher/dest if closed
                alt, alt_rev = find_road(self.roads_geom, fr, "CRUSHER")
                if alt and alt.code != road.code:
                    truck.active_road_code = alt.code
                    truck.road_reverse = alt_rev
                    truck.road_distance_km = alt.distance_km
                    truck.road_speed_limit = alt.speed_limit_kmh
                    self.world.log_sim(
                        self.clock.sim_now,
                        f"{truck.code} rerouted via {alt.code} (road closed)",
                        "EQUIPMENT",
                        truck.code,
                    )
                else:
                    truck.road_speed_limit = max(5.0, road.speed_limit_kmh * 0.3)
            else:
                truck.road_speed_limit = road.speed_limit_kmh
        else:
            log.error(
                "%s: no road found from %s to %s — assignment blocked",
                truck.code,
                fr,
                to,
            )
            truck.active_road_code = None
            truck.speed_kmh = 0

    def _command_ctx(self) -> CommandContext:
        tick_sim_sec = self.cfg.tick_seconds * self.clock.speed
        return CommandContext(
            world=self.world,
            session=self.session,
            sim_now=self.clock.sim_now,
            open_states=self.open_states,
            equip_id_by_code=self.equip_id_by_code,
            zone_id_by_code=self.zone_id_by_code,
            site_id=self.site_id or 0,
            causal_scenarios=self.causal_scenarios,
            causal_min_duration_min=8.0 * tick_sim_sec / 60.0,
            causal_tick_sim_sec=tick_sim_sec,
            zones_geom=self.zones_geom,
            equipment_by_id=self._equipment_by_id,
            causal_seed=self.cfg.random_seed,
            on_causal_recovery=lambda run_id, target_id, recovered_at: self._close_failure_recovery(
                run_id=run_id,
                target_id=target_id,
                recovered_at=recovered_at,
            ),
        )

    def _persist_control(self) -> None:
        write_control(
            {
                "status": self.clock.status,
                "speed": self.clock.speed,
                "seed": self.cfg.random_seed,
                "mode": self.world.mode,
                "scenario": self.cfg.scenario,
                "sim_now": self.clock.sim_now.isoformat(),
                "note": "Simulateur intégré à l'API — contrôlez depuis le Centre de simulation.",
            }
        )
        self.world.write_runtime_snapshot(
            self.clock.sim_now,
            self.clock.status,
            self.clock.speed,
            causal_scenarios=self.causal_scenarios.developer_status(include_hidden=True),
            compact=self.cfg.batch_generation,
        )

    def _load_commands(self):
        if not self.cfg.batch_generation:
            return load_all_commands()
        try:
            mtime = COMMANDS_PATH.stat().st_mtime
        except OSError:
            return []
        if self._commands_mtime == mtime:
            return self._commands_cache
        self._commands_mtime = mtime
        self._commands_cache = load_all_commands()
        return self._commands_cache

    def _transition_truck(self, truck: TruckRuntime, *, sim_now: datetime | None = None, **kwargs):
        return transition_truck(
            self.session,
            self.open_states,
            truck,
            sim_now or self.clock.sim_now,
            self.site_id or 0,
            zones=self.zones_geom,
            equipment=self._equipment_by_id.get(truck.equipment_id),
            **kwargs,
        )

    def _flush_telemetry_batch(self) -> None:
        if self._pending_positions:
            self.session.execute(insert(EquipmentPosition), self._pending_positions)
            self._pending_positions.clear()
        if self._pending_telemetry:
            self.session.execute(insert(EquipmentTelemetry), self._pending_telemetry)
            self._pending_telemetry.clear()
        if self._pending_tyres:
            stmt = pg_insert(TyreTelemetry).values(self._pending_tyres)
            self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["equipment_id", "ts", "position"],
                    set_={
                        "pressure_kpa": stmt.excluded.pressure_kpa,
                        "temperature_c": stmt.excluded.temperature_c,
                    },
                )
            )
            self._pending_tyres.clear()

    def _end_tick_persist(self) -> None:
        commit_every = max(1, self.cfg.commit_every_ticks)
        persist_every = max(1, self.cfg.persist_control_every_ticks)
        should_commit = (not self.cfg.batch_generation) or (self._tick_count % commit_every == 0)
        should_control = (not self.cfg.batch_generation) or (self._tick_count % persist_every == 0)
        if should_commit:
            self._flush_telemetry_batch()
            self.session.commit()
        if should_control:
            self._persist_control()

    def _commit_pending(self, *, persist_control: bool = True) -> None:
        self._flush_telemetry_batch()
        self.session.commit()
        if persist_control:
            self._persist_control()

    def _ensure_assignments(self) -> None:
        operators = list(self.session.scalars(select(Operator).order_by(Operator.operator_id)).all())
        if not operators:
            return

        for i, truck in enumerate(self.world.trucks.values()):
            op = operators[i % len(operators)]
            asn = self.session.scalar(
                select(EquipmentAssignment)
                .where(
                    EquipmentAssignment.truck_id == truck.equipment_id,
                    EquipmentAssignment.status == "ACTIVE",
                )
                .order_by(EquipmentAssignment.assigned_at.desc())
                .limit(1)
            )
            if asn:
                if asn.operator_id is None:
                    asn.operator_id = op.operator_id
                if asn.shift_id == self.shift_id:
                    continue
                asn.status = "COMPLETED"
                asn.completed_at = self.clock.sim_now
            self.session.add(
                EquipmentAssignment(
                    shift_id=self.shift_id,
                    truck_id=truck.equipment_id,
                    loader_id=self.equip_id_by_code.get(truck.loader_code),
                    operator_id=op.operator_id,
                    origin_zone_id=self.zone_id_by_code.get(truck.origin_zone_code),
                    destination_zone_id=self.zone_id_by_code.get(truck.dest_zone_code),
                    material_id=self.material_id,
                    assigned_at=self.clock.sim_now,
                    started_at=self.clock.sim_now,
                    source="FMS",
                    status="ACTIVE",
                )
            )
        self.session.flush()

    def _apply_scenario_side_effects(self, newly_started: list[str]) -> None:
        for sid in newly_started:
            if sid == "exc_breakdown":
                exc_id = self.equip_id_by_code.get("EXC-002")
                if exc_id:
                    self.session.add(
                        MaintenanceEvent(
                            equipment_id=exc_id,
                            type="BREAKDOWN",
                            component="Hydraulic pump",
                            description="Excavator EXC-002 mechanical stop",
                            start_time=self.clock.sim_now,
                            severity=AlertSeverity.CRITICAL,
                            status="OPEN",
                            planned=False,
                        )
                    )
                    eq = self.session.get(Equipment, exc_id)
                    if eq:
                        eq.current_state = EquipmentState.STOPPED_MECHANICAL
                    emit_fms_alert(
                        self.session,
                        self.clock.sim_now,
                        "EQUIPMENT_BREAKDOWN",
                        "EXC-002 arrêt matériel",
                        "Pelle EXC-002 — panne hydraulique, chargement Banc B interrompu.",
                        exc_id,
                        self.zone_id_by_code.get("BANC_B"),
                        AlertSeverity.CRITICAL,
                    )
            elif sid == "comm_loss":
                emit_fms_alert(
                    self.session,
                    self.clock.sim_now,
                    "COMMUNICATION_LOSS",
                    "TRK-004 perte communication",
                    "Camion TRK-004 — aucune télémétrie reçue.",
                    self.equip_id_by_code.get("TRK-004"),
                    severity=AlertSeverity.WARNING,
                )
            elif sid == "unexplained_stop":
                emit_fms_alert(
                    self.session,
                    self.clock.sim_now,
                    "UNEXPLAINED_STOP",
                    "TRK-012 arrêt non défini",
                    "Camion TRK-012 arrêté hors zone connue — raison non confirmée.",
                    self.equip_id_by_code.get("TRK-012"),
                    severity=AlertSeverity.WARNING,
                )

        # Recovery side effects
        if "exc_breakdown:recover" in self.world.scenario_events_fired and "EXC-002" not in self.world.excavators_down:
            exc_id = self.equip_id_by_code.get("EXC-002")
            if exc_id:
                eq = self.session.get(Equipment, exc_id)
                if eq and eq.current_state == EquipmentState.STOPPED_MECHANICAL:
                    eq.current_state = EquipmentState.STOPPED_OPERATIONAL
                self.session.execute(
                    text(
                        "UPDATE maintenance_events SET status='CLOSED', actual_end_time=:ts "
                        "WHERE equipment_id=:eid AND status='OPEN'"
                    ),
                    {"ts": self.clock.sim_now, "eid": exc_id},
                )
                emit_system_event(
                    self.session, self.clock.sim_now, "EQUIPMENT_RECOVERED", exc_id, "EXC-002 back online"
                )

    def tick(self) -> None:
        from simulator.commands import command_transaction
        from simulator.control import control_transaction

        with command_transaction(), control_transaction:
            self._tick()

    def _tick(self) -> None:
        if not self.cfg.batch_generation:
            self._sync_control_from_disk()
        self._tick_count += 1
        if not self.cfg.batch_generation:
            write_heartbeat(self.clock.sim_now, self._tick_count, self.clock.status)

        ctx = self._command_ctx()
        # Zone/road commands + expiry (always, including when paused)
        process_pending_commands(ctx)
        # Never rewrite a snapshot captured before zone/loader status updates.
        all_cmds = self._load_commands()

        if self.clock.status != "RUNNING":
            # Apply truck equipment commands even when paused (no motion advance)
            all_cmds = self._load_commands()
            for truck in self.world.trucks.values():
                process_equipment_commands(ctx, truck.code, all_cmds)
            self._end_tick_persist()
            return

        # Causal scenarios progress independently of legacy/manual fault
        # injection. They mutate normal runtime signals; only resulting
        # operational records are persisted below.
        population_update = self.failure_population.advance(
            self.world,
            self.causal_scenarios,
            self.clock.sim_now,
        )
        for incident in population_update.recovered:
            self._persist_failure_recovery(incident)
        self._persist_causal_transitions(list(population_update.transitions))
        self.world.refresh_operating_conditions(self.clock.sim_now)

        # Auto scenarios only outside MANUAL mode
        if self.world.mode != "MANUAL":
            newly = apply_scenarios(self.world, self.clock.sim_now, self.cfg.scenario)
            self._apply_scenario_side_effects(newly)

        active_trucks = 0
        active_loaders = sum(1 for l in self.world.loaders.values() if l.effective_capacity() > 0)

        for code, truck in self.world.trucks.items():
            if truck.code not in self.open_states:
                self._transition_truck(truck)
                if truck.phase in CYCLE_PHASES and truck.code not in self.open_cycles:
                    self._start_cycle(truck)
                    self._open_cycle_stage(truck, truck.db_state())

            # Loader / excavator capacity
            ldr = self.world.loader_for_truck(truck)
            if ldr and ldr.effective_capacity() <= 0 and truck.phase == TruckPhase.LOADING:
                ldr.release_service(truck.code, requeue=True)
                truck.phase = TruckPhase.WAITING_LOADING
                truck.speed_kmh = 0
                truck.hold_for_next_tick(self.cfg)
                self.world.log_sim(
                    self.clock.sim_now,
                    f"{truck.code} waiting — loader {truck.loader_code} unavailable",
                    "EQUIPMENT",
                    truck.code,
                )

            # Zone capacity: cannot start loading if bench full
            if truck.phase == TruckPhase.WAITING_LOADING:
                zone = self.world.zones.get(truck.origin_zone_code)
                if zone:
                    if not zone.enter(truck.code):
                        truck.phase_ticks_left = max(truck.phase_ticks_left, 3)
                        qlen = len(zone.queue)
                        if self._last_queue_log.get(zone.code) != qlen and qlen >= 2:
                            self.world.log_sim(
                                self.clock.sim_now,
                                f"{zone.name} queue increased to {qlen}",
                                "ZONE",
                                zone.code,
                            )
                            self._last_queue_log[zone.code] = qlen

            # 1. Capture phase before any command mutation
            prev_phase = truck.phase

            # 2. Apply pending equipment commands for this truck (persists DB transition)
            process_equipment_commands(ctx, truck.code, all_cmds)
            prev_phase = truck.phase

            # Block advance into LOADING if cannot load
            if (
                truck.phase == TruckPhase.WAITING_LOADING
                and not self.world.truck_may_load(truck)
            ):
                truck.hold_for_next_tick(self.cfg)
            else:
                if (
                    ldr
                    and truck.phase == TruckPhase.WAITING_LOADING
                    and truck.next_loading_duration_seconds is None
                ):
                    truck.next_loading_duration_seconds = ldr.sample_loading_seconds(
                        self.cfg.cycle_dynamics
                    )
                truck.advance_phase(
                    self.cfg,
                    loading_rate=ldr.loading_rate() if ldr else 1.0,
                    loading_duration_seconds=truck.next_loading_duration_seconds,
                )

            phase_after_advance = truck.phase

            left_loader_service = prev_phase == TruckPhase.LOADING and truck.phase != TruckPhase.LOADING
            abandoned_loader_service = (
                ldr is not None
                and ldr.active_truck_code == truck.code
                and truck.phase not in (TruckPhase.WAITING_LOADING, TruckPhase.LOADING)
            )
            if left_loader_service or abandoned_loader_service:
                if ldr:
                    ldr.release_service(truck.code)
                zone = self.world.zones.get(truck.origin_zone_code)
                if zone:
                    zone.leave(truck.code)

            if truck.phase != prev_phase and truck.is_moving():
                self._bind_road(truck)

            sample_due = (
                self._tick_count % max(1, self.cfg.persistence_sample_every_ticks) == 0
            )
            if not truck.comm_lost:
                self._update_position(truck)
                if sample_due:
                    self._write_position(truck)
                    tel = build_telemetry(truck)
                    if tel:
                        self._write_telemetry(truck, tel)
                        self._write_tyres(truck)
                        self._check_oem_anomalies(truck, tel)
            if not truck.comm_lost and (truck.speed_kmh > 0 or truck.phase != TruckPhase.NO_COMM):
                active_trucks += 1

            if prev_phase == TruckPhase.REFUELING and truck.phase == TruckPhase.WAITING_LOADING:
                self._record_fuel_event(truck)

            if truck.phase == TruckPhase.MOVING_LOADED and prev_phase != TruckPhase.MOVING_LOADED:
                self._open_trip(truck)

            dump_completed = (
                prev_phase == TruckPhase.DUMPING
                and truck.payload_t <= 0
                and truck.phase != TruckPhase.DUMPING
            )
            if dump_completed:
                self._complete_dump(truck, active_trucks, active_loaders)

            if PHASE_TO_DB.get(prev_phase) != PHASE_TO_DB.get(phase_after_advance):
                self._transition_truck(truck)
                self._handle_cycle_transition(truck, prev_phase)
                if truck.phase != prev_phase:
                    self.world.log_sim(
                        self.clock.sim_now,
                        f"{truck.code} {prev_phase.value} → {truck.phase.value}",
                        "EQUIPMENT",
                        truck.code,
                    )

        for code, ldr in self.world.loaders.items():
            eid = self.equip_id_by_code.get(code)
            if not eid:
                continue
            new_state = loader_db_state(ldr)
            if self._loader_persisted_state.get(code) == new_state:
                continue
            transition_loader(
                self.session,
                self.open_states,
                ldr,
                self.clock.sim_now,
                equipment=self._equipment_by_id.get(eid),
            )
            self._loader_persisted_state[code] = new_state

        self.clock.advance()
        self._end_tick_persist()

    def _update_position(self, truck: TruckRuntime) -> None:
        origin = self.zones_geom.get(truck.origin_zone_code)
        dest = self.zones_geom.get(truck.dest_zone_code)
        if truck.is_moving():
            road = None
            if truck.active_road_code:
                road = self.roads_geom.get(truck.active_road_code)
            if road:
                lng, lat, hdg = interpolate_linestring(
                    road.line, truck.road_progress, reverse=truck.road_reverse
                )
                truck.lng, truck.lat, truck.heading_deg = lng, lat, hdg
            elif origin and dest:
                # Should not happen if roads seeded; snap progress between centroids
                o, d = origin.centroid, dest.centroid
                t = truck.road_progress
                truck.lng = o[0] + (d[0] - o[0]) * t
                truck.lat = o[1] + (d[1] - o[1]) * t
        elif truck.phase in (TruckPhase.WAITING_LOADING, TruckPhase.LOADING) and origin:
            truck.lng, truck.lat = origin.centroid
            truck.heading_deg = 0
        elif truck.phase in (TruckPhase.WAITING_DUMPING, TruckPhase.DUMPING) and dest:
            truck.lng, truck.lat = dest.centroid
            truck.heading_deg = 180
        elif truck.phase == TruckPhase.REFUELING and truck.road_progress >= 1.0:
            fuel = self.zones_geom.get("FUEL")
            if fuel:
                truck.lng, truck.lat = fuel.centroid

    def _write_position(self, truck: TruckRuntime) -> None:
        zone_id = resolve_zone_id(
            self.session,
            self.site_id or 0,
            truck.lng,
            truck.lat,
            moving=truck.is_moving() and truck.road_progress < 1.0,
            zones=self.zones_geom,
        )
        self._pending_positions.append(
            {
                "equipment_id": truck.equipment_id,
                "ts": self.clock.sim_now,
                "position": point_wkt(truck.lng, truck.lat),
                "speed_kmh": Decimal(str(round(truck.speed_kmh, 1))),
                "heading_deg": Decimal(str(round(truck.heading_deg, 1))),
                "zone_id": zone_id,
                "metadata_": {},
            }
        )

    def _write_telemetry(self, truck: TruckRuntime, tel: dict) -> None:
        self._pending_telemetry.append(
            {
                "equipment_id": truck.equipment_id,
                "ts": self.clock.sim_now,
                "raw_data": {},
                **tel,
            }
        )

    def _write_tyres(self, truck: TruckRuntime) -> None:
        for row in tyre_rows(truck):
            self._pending_tyres.append(
                {
                    "equipment_id": truck.equipment_id,
                    "ts": self.clock.sim_now,
                    "position": row["position"],
                    "pressure_kpa": row["pressure_kpa"],
                    "temperature_c": row["temperature_c"],
                }
            )

    def _check_oem_anomalies(self, truck: TruckRuntime, tel: dict) -> None:
        from app.oem.catalog import SIM_ERROR_CODES
        from app.oem.thresholds import classify_value, expected_range

        checks: list[tuple[str, str, float]] = [
            ("engine_temp_c", "SIM-ENG-TEMP-HIGH", float(tel.get("engine_temp_c") or 0)),
            ("oil_pressure_kpa", "SIM-OIL-PRESS-LOW", float(tel.get("oil_pressure_kpa") or 0)),
            ("battery_voltage", "SIM-BATT-VOLT-LOW", float(tel.get("battery_voltage") or 0)),
            ("fuel_rate_lph", "SIM-FUEL-RATE-HIGH", float(tel.get("fuel_rate_lph") or 0)),
            ("communication_quality", "SIM-COMM-QUALITY-LOW", float(tel.get("communication_quality") or 0)),
        ]
        for key, code, value in checks:
            level = classify_value(key, value)
            if level:
                self._emit_oem_code(truck, code, key, value, level)
            else:
                truck.active_oem_codes.discard(f"{code}:")

        for pos, tyre in (truck.tyres or {}).items():
            p = float(tyre["pressure_kpa"])
            t = float(tyre["temperature_c"])
            if classify_value("tyre_pressure_kpa", p):
                self._emit_oem_code(truck, "SIM-TYRE-PRESS-LOW", "tyre_pressure_kpa", p, "warning", pos)
            else:
                truck.active_oem_codes.discard(f"SIM-TYRE-PRESS-LOW:{pos}")
            if classify_value("tyre_temp_c", t):
                self._emit_oem_code(truck, "SIM-TYRE-TEMP-HIGH", "tyre_temp_c", t, "warning", pos)
            else:
                truck.active_oem_codes.discard(f"SIM-TYRE-TEMP-HIGH:{pos}")

    def _emit_oem_code(
        self,
        truck: TruckRuntime,
        code: str,
        key: str,
        value: float,
        level: str,
        position: str | None = None,
    ) -> None:
        from app.oem.catalog import SIM_ERROR_CODES
        from app.oem.thresholds import expected_range

        token = f"{code}:{position or ''}"
        if token in truck.active_oem_codes:
            return
        truck.active_oem_codes.add(token)
        lo, hi = expected_range(key)
        meta = SIM_ERROR_CODES.get(code, {})
        emit_system_event(
            self.session,
            self.clock.sim_now,
            code,
            truck.equipment_id,
            f"{truck.code} {meta.get('label', code)} ({value})",
            raw_data={
                "code": code,
                "parameter": key,
                "value": value,
                "expectedLow": lo,
                "expectedHigh": hi,
                "severity": "CRITICAL" if level == "critical" else meta.get("severity", "WARNING"),
                "category": meta.get("category"),
                "status": "ACTIVE",
                "source": "simulation/test",
                "position": position,
            },
        )

    def _transition_state(self, truck: TruckRuntime) -> None:
        """Deprecated — delegates to transition_service."""
        self._transition_truck(truck)

    def _close_cycle_stage(self, truck: TruckRuntime) -> None:
        sid = self.open_cycle_stages.pop(truck.code, None)
        if not sid:
            return
        stage = self.session.get(CycleStage, sid)
        if stage and stage.end_time is None:
            stage.end_time = self.clock.sim_now
            stage.duration_sec = int((self.clock.sim_now - stage.start_time).total_seconds())

    def _open_cycle_stage(self, truck: TruckRuntime, state: EquipmentState) -> None:
        cid = self.open_cycles.get(truck.code)
        if not cid:
            return
        seq = STAGE_SEQUENCE.get(state)
        if seq is None:
            return
        existing = self.session.scalar(
            select(CycleStage).where(CycleStage.cycle_id == cid, CycleStage.sequence_no == seq)
        )
        if existing:
            # Re-enter same stage after interruption (e.g. loader down → wait → load)
            if existing.end_time is not None:
                existing.end_time = None
                existing.duration_sec = None
                existing.start_time = self.clock.sim_now
            self.open_cycle_stages[truck.code] = existing.cycle_stage_id
            return
        zone_id = None
        if state in (EquipmentState.WAITING_LOADING, EquipmentState.LOADING):
            zone_id = self.zone_id_by_code.get(truck.origin_zone_code)
        elif state in (EquipmentState.WAITING_DUMPING, EquipmentState.DUMPING):
            zone_id = self.zone_id_by_code.get(truck.dest_zone_code)
        row = CycleStage(
            cycle_id=cid,
            stage=state,
            start_time=self.clock.sim_now,
            sequence_no=seq,
            zone_id=zone_id,
        )
        self.session.add(row)
        self.session.flush()
        self.open_cycle_stages[truck.code] = row.cycle_stage_id

    def _handle_cycle_transition(self, truck: TruckRuntime, prev_phase: TruckPhase) -> None:
        if truck.phase not in CYCLE_PHASES:
            self._close_cycle_stage(truck)
            return
        if truck.code not in self.open_cycles:
            self._start_cycle(truck)
        self._close_cycle_stage(truck)
        self._open_cycle_stage(truck, truck.db_state())

    def _start_cycle(self, truck: TruckRuntime) -> None:
        from simulator.shifts import ensure_simulation_shift

        previous_shift_id = self.shift_id
        shift = ensure_simulation_shift(
            self.session,
            site_id=self.site_id or 0,
            material_id=self.material_id,
            sim_now=self.clock.sim_now,
        )
        self.shift_id = shift.shift_id
        if previous_shift_id != self.shift_id:
            self._ensure_assignments()
        c = Cycle(
            shift_id=shift.shift_id,
            truck_id=truck.equipment_id,
            loader_id=self.equip_id_by_code.get(truck.loader_code),
            origin_zone_id=self.zone_id_by_code.get(truck.origin_zone_code),
            destination_zone_id=self.zone_id_by_code.get(truck.dest_zone_code),
            material_id=self.material_id,
            started_at=self.clock.sim_now,
            status="ACTIVE",
            metadata_={"source": "SIMULATOR"},
        )
        self.session.add(c)
        self.session.flush()
        self.open_cycles[truck.code] = c.cycle_id
        emit_system_event(self.session, self.clock.sim_now, "CYCLE_STARTED", truck.equipment_id, truck.code)

    def _open_trip(self, truck: TruckRuntime) -> None:
        road, _ = find_road(self.roads_geom, truck.origin_zone_code, truck.dest_zone_code)
        dist = Decimal(str(road.distance_km)) if road else Decimal(str(truck.road_distance_km))
        trip = Trip(
            shift_id=self.shift_id,
            truck_id=truck.equipment_id,
            cycle_id=self.open_cycles.get(truck.code),
            material_id=self.material_id,
            origin_zone_id=self.zone_id_by_code.get(truck.origin_zone_code),
            destination_zone_id=self.zone_id_by_code.get(truck.dest_zone_code),
            start_time=self.clock.sim_now,
            payload_t=Decimal(str(round(truck.payload_t, 1))),
            distance_km=dist,
            status="ACTIVE",
        )
        self.session.add(trip)
        self.session.flush()
        self.open_trips[truck.code] = trip.trip_id

    def _record_fuel_event(self, truck: TruckRuntime) -> None:
        self.session.add(
            FuelEvent(
                equipment_id=truck.equipment_id,
                station_zone_id=self.zone_id_by_code.get("FUEL"),
                ts=self.clock.sim_now,
                liters_added=Decimal("800"),
                fuel_before_pct=Decimal(str(round(max(0, truck.fuel_pct - 40), 1))),
                fuel_after_pct=Decimal(str(round(truck.fuel_pct, 1))),
                duration_sec=300,
            )
        )
        emit_system_event(
            self.session, self.clock.sim_now, "REFUEL_COMPLETE", truck.equipment_id, truck.code
        )

    def _complete_dump(self, truck: TruckRuntime, active_trucks: int, active_loaders: int) -> None:
        # Payload is already emptied by dump animation; prefer trip/cycle recorded load.
        cid = self.open_cycles.get(truck.code)
        tid = self.open_trips.get(truck.code)
        payload = float(truck.payload_t or 0)
        if tid:
            trip_peek = self.session.get(Trip, tid)
            if trip_peek and trip_peek.payload_t is not None and float(trip_peek.payload_t) > payload:
                payload = float(trip_peek.payload_t)
        if payload <= 0:
            payload = float(self.cfg.default_truck_payload)
        self._close_cycle_stage(truck)
        cid = self.open_cycles.pop(truck.code, None)
        tid = self.open_trips.pop(truck.code, None)
        road, _ = find_road(self.roads_geom, truck.origin_zone_code, truck.dest_zone_code)
        dist = Decimal(str(road.distance_km)) if road else Decimal(str(truck.road_distance_km))
        if tid:
            trip = self.session.get(Trip, tid)
            if trip:
                trip.end_time = self.clock.sim_now
                trip.payload_t = Decimal(str(payload))
                trip.distance_km = dist
                trip.status = "COMPLETED"
        production_shift_id = self.shift_id
        if cid:
            cycle = self.session.get(Cycle, cid)
            if cycle:
                cycle.completed_at = self.clock.sim_now
                cycle.payload_t = Decimal(str(payload))
                cycle.distance_km = dist
                cycle.status = "COMPLETED"
                cycle.total_duration_sec = int((self.clock.sim_now - cycle.started_at).total_seconds())
                self.completed_cycle_count += 1
                production_shift_id = cycle.shift_id
        record_dump_production(
            self.session,
            production_shift_id,
            self.clock.sim_now,
            payload,
            self.zone_id_by_code.get(truck.origin_zone_code),
            self.zone_id_by_code.get(truck.dest_zone_code),
            self.material_id,
            active_trucks,
            active_loaders,
        )
        emit_system_event(self.session, self.clock.sim_now, "CYCLE_COMPLETED", truck.equipment_id, truck.code)
        log.info("%s completed dump — %.1f t (%.2f km)", truck.code, payload, float(dist))

    def start(self) -> None:
        self.clock.start()
        self._persist_control()

    def _persist_causal_transitions(
        self,
        transitions: list[ObservableTransition],
    ) -> None:
        for transition in transitions:
            if transition.stage.value != "INCIDENT":
                continue
            equipment_id = self.equip_id_by_code.get(transition.target_id)
            emit_system_event(
                self.session,
                transition.occurred_at,
                transition.event_kind,
                equipment_id,
                transition.description or transition.title or transition.event_kind,
            )
            if transition.alert_type:
                severity = AlertSeverity[transition.severity or "WARNING"]
                emit_fms_alert(
                    self.session,
                    transition.occurred_at,
                    transition.alert_type,
                    transition.title or transition.alert_type,
                    transition.description or "Operational condition requires review.",
                    equipment_id,
                    severity=severity,
                )
            if transition.maintenance_required and equipment_id:
                truck = self.world.trucks.get(transition.target_id)
                if truck is not None and (truck.mechanical_hold or truck.in_maintenance):
                    self._interrupt_truck_work(
                        truck,
                        interrupted_at=transition.occurred_at,
                    )
                    # Persist the authoritative operational state at the
                    # incident timestamp.  Waiting for a later phase change
                    # can lose the entire STOPPED_MECHANICAL interval.
                    truck.phase = TruckPhase.STOPPED
                    truck.speed_kmh = 0.0
                    self._transition_truck(truck, sim_now=transition.occurred_at)
                    population_incident = self.failure_population.active.get(transition.run_id)
                    expected_recovery_at = (
                        population_incident.recovery_due_at
                        if population_incident and population_incident.recovery_due_at
                        else transition.occurred_at + timedelta(minutes=30)
                    )
                    records = start_mechanical_incident(
                        self.session,
                        equipment_id=equipment_id,
                        started_at=transition.occurred_at,
                        expected_recovery_at=expected_recovery_at,
                        severity=AlertSeverity.CRITICAL,
                    )
                    self.open_failure_records[transition.run_id] = records
                else:
                    self.session.add(
                        MaintenanceEvent(
                            equipment_id=equipment_id,
                            type="UNPLANNED_STOP",
                            component=None,
                            description="Unplanned stop pending inspection and diagnosis.",
                            start_time=transition.occurred_at,
                            severity=AlertSeverity.CRITICAL,
                            status="OPEN",
                            planned=False,
                        )
                    )

    def _interrupt_truck_work(
        self,
        truck: TruckRuntime,
        *,
        interrupted_at: datetime,
    ) -> None:
        """Close in-flight work without converting interruption into a target."""

        from simulator.cycle_lifecycle import interrupt_active_truck_work

        interrupt_active_truck_work(
            self.session,
            cycle_id=self.open_cycles.pop(truck.code, None),
            stage_id=self.open_cycle_stages.pop(truck.code, None),
            trip_id=self.open_trips.pop(truck.code, None),
            interrupted_at=interrupted_at,
            reason="MECHANICAL_INCIDENT",
        )
        loader = self.world.loader_for_truck(truck)
        if loader is not None:
            loader.release_service(truck.code, requeue=False)
        zone = self.world.zones.get(truck.origin_zone_code)
        if zone is not None:
            zone.leave(truck.code)

    def _persist_failure_recovery(self, incident: PopulationIncident) -> None:
        self._close_failure_recovery(
            run_id=incident.run_id,
            target_id=incident.target_id,
            recovered_at=incident.recovered_at or self.clock.sim_now,
        )

    def _close_failure_recovery(
        self,
        *,
        run_id: str,
        target_id: str,
        recovered_at: datetime,
    ) -> None:
        records = self.open_failure_records.pop(run_id, None)
        if records is None:
            return
        recover_mechanical_incident(
            self.session,
            records,
            recovered_at=recovered_at,
        )
        truck = self.world.trucks.get(target_id)
        if truck is None:
            return
        self._bind_road(truck)
        self._transition_truck(truck, sim_now=recovered_at)
        if truck.phase in CYCLE_PHASES and truck.code not in self.open_cycles:
            self._start_cycle(truck)
            self._open_cycle_stage(truck, truck.db_state())
        emit_system_event(
            self.session,
            recovered_at,
            "EQUIPMENT_RECOVERED",
            truck.equipment_id,
            f"{truck.code} returned to service after inspection.",
        )

    def pause(self) -> None:
        self.clock.pause()
        self._commit_pending(persist_control=True)

    def resume(self) -> None:
        self.clock.resume()
        self._persist_control()

    def interrupt_open_cycles(self, *, reason: str) -> dict[str, int]:
        """Close unfinished synthetic work without turning it into an ML target."""

        from simulator.cycle_lifecycle import interrupt_active_simulation_cycles

        self._flush_telemetry_batch()
        counts = interrupt_active_simulation_cycles(
            self.session,
            site_id=self.site_id or 0,
            interrupted_at=self.clock.sim_now,
            reason=reason,
        )
        self.open_cycles.clear()
        self.open_cycle_stages.clear()
        self.open_trips.clear()
        self.session.commit()
        return counts

    def reset(self) -> None:
        from app.monitoring.coordination import monitoring_reset_coordinator
        from simulator.commands import command_transaction
        from simulator.control import control_transaction

        with command_transaction(), control_transaction, monitoring_reset_coordinator.reset_guard():
            self.causal_scenarios.reset(self.world)
            self.failure_population.reset()
            self._clear_dynamic_data()
            self.world.clear_scenario_memory()
            clear_commands()
            clear_event_log()
            self.open_states.clear()
            self.open_cycles.clear()
            self.open_cycle_stages.clear()
            self.open_trips.clear()
            self.open_failure_records.clear()
            self._pending_positions.clear()
            self._pending_telemetry.clear()
            self._pending_tyres.clear()
            self._commands_mtime = None
            self._commands_cache = []
            self._shift_spec_key = None
            self._last_queue_log.clear()
            self._tick_count = 0
            self.completed_cycle_count = 0
            self.startup_interrupted_cycles = 0
            self.clock.reset()
            self._persist_control()
            self._boot()
            self.world.log_test(self.clock.sim_now, "Simulation reset", "SYSTEM", None)

    def activate_causal_scenario(
        self,
        scenario_id: str,
        target_id: str,
        *,
        duration_min: float | None = None,
        seed: int | None = None,
    ) -> dict:
        try:
            spec = SCENARIO_SPECS[scenario_id]
        except KeyError as exc:
            raise ValueError(f"Unknown causal scenario: {scenario_id}") from exc
        min_duration_min = 8.0 * self.cfg.tick_seconds * self.clock.speed / 60.0
        effective_duration = duration_min
        if effective_duration is None:
            effective_duration = max(spec.default_duration_min, min_duration_min)
        elif effective_duration < min_duration_min:
            raise ValueError(
                "duration_min is too short for the current simulation speed; "
                f"use at least {min_duration_min:.1f} simulated minutes"
            )
        run = self.causal_scenarios.activate(
            self.world,
            scenario_id,
            target_id,
            self.clock.sim_now,
            duration_min=effective_duration,
            seed=self.cfg.random_seed if seed is None else seed,
        )
        self._persist_control()
        self.world.log_test(
            self.clock.sim_now,
            f"Causal scenario {scenario_id} activated for {target_id}",
            "EQUIPMENT",
            target_id,
        )
        return run.developer_status(include_hidden=True)

    def stop_causal_scenario(self, run_id: str) -> dict:
        run = self.causal_scenarios.stop(self.world, run_id)
        self._close_failure_recovery(
            run_id=run.run_id,
            target_id=run.target_id,
            recovered_at=self.clock.sim_now,
        )
        self._persist_control()
        self.world.log_test(
            self.clock.sim_now,
            f"Causal scenario stopped for {run.target_id}",
            "EQUIPMENT",
            run.target_id,
        )
        return run.developer_status(include_hidden=True)

    def _clear_dynamic_data(self) -> None:
        from simulator.reset_cleanup import clear_simulation_run_data

        counts = clear_simulation_run_data(self.session)
        self.session.commit()
        log.info("Dynamic simulation data cleared: %s", counts)
