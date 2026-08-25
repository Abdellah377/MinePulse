"""Declarative registry of simulation command actions and their effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.db.enums import AlertSeverity
from simulator.loaders import LoaderRuntime
from simulator.queues import RoadRuntime, ZoneRuntime
from simulator.state_machine import TruckPhase, TruckRuntime
from simulator.world_model import SimulationWorld

# Aliases map user-facing action names to canonical registry keys
ACTION_ALIASES: dict[str, str] = {
    "BREAKDOWN": "MECHANICAL_BREAKDOWN",
    "UNDEFINED_STOP": "STOP_UNDEFINED",
    "SIMULATE_SLOW_TRAFFIC": "SLOW_TRAFFIC",
    "RESTRICT_ROAD": "CHANGE_SPEED_LIMIT",
    "GPS_LOSS": "COMMUNICATION_LOSS",  # GPS loss treated as comm loss in v1
}


@dataclass
class AlertSpec:
    alert_type: str
    title_template: str
    description_template: str
    severity: AlertSeverity = AlertSeverity.WARNING
    resolve_on_restore: bool = True


@dataclass
class ActionSpec:
    action: str
    target_types: tuple[str, ...]
    event_type: str
    alert: AlertSpec | None = None
    equipment_subtype: str | None = None  # HAUL_TRUCK | LOADER | EXCAVATOR | None=all


def canonical_action(action: str) -> str:
    a = action.upper()
    return ACTION_ALIASES.get(a, a)


# ---------------------------------------------------------------------------
# Capture original state (for safe recovery)
# ---------------------------------------------------------------------------


def capture_truck(truck: TruckRuntime) -> dict[str, Any]:
    return {
        "phase": truck.phase.value,
        "speed_kmh": truck.speed_kmh,
        "comm_lost": truck.comm_lost,
        "unexplained_hold": truck.unexplained_hold,
        "mechanical_hold": truck.mechanical_hold,
        "pre_stop_phase": truck.pre_stop_phase.value if truck.pre_stop_phase else None,
        "fuel_pct": truck.fuel_pct,
        "engine_off": getattr(truck, "engine_off", False),
        "gps_lost": getattr(truck, "gps_lost", False),
        "high_engine_temp": getattr(truck, "high_engine_temp", False),
        "in_maintenance": getattr(truck, "in_maintenance", False),
        "low_oil_pressure": getattr(truck, "low_oil_pressure", False),
        "battery_low": getattr(truck, "battery_low", False),
        "fuel_rate_factor": getattr(truck, "fuel_rate_factor", 1.0),
        "sensor_signal_loss": getattr(truck, "sensor_signal_loss", False),
        "comm_quality_drop": getattr(truck, "comm_quality_drop", False),
        "tyre_pressure_low": getattr(truck, "tyre_pressure_low", False),
        "tyre_temp_high": getattr(truck, "tyre_temp_high", False),
        "tyre_fault_position": getattr(truck, "tyre_fault_position", None),
    }


def capture_loader(ldr: LoaderRuntime) -> dict[str, Any]:
    return {
        "available": ldr.available,
        "capacity_factor": ldr.capacity_factor,
        "mechanical_breakdown": ldr.mechanical_breakdown,
        "communication_lost": ldr.communication_lost,
        "slow_loading": getattr(ldr, "slow_loading", False),
        "in_maintenance": getattr(ldr, "in_maintenance", False),
    }


def capture_zone(zone: ZoneRuntime) -> dict[str, Any]:
    return {
        "capacity": zone.capacity,
        "closed": zone.closed,
        "arrival_pressure": getattr(zone, "arrival_pressure", 1.0),
    }


def capture_road(road: RoadRuntime) -> dict[str, Any]:
    return {
        "closed": road.closed,
        "speed_limit": road.speed_limit,
        "slow_traffic_factor": road.slow_traffic_factor,
    }


# ---------------------------------------------------------------------------
# Runtime apply effects
# ---------------------------------------------------------------------------


def _apply_truck_comm_loss(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.comm_lost = True
    truck.gps_lost = True
    truck.phase = TruckPhase.NO_COMM
    truck.speed_kmh = 0


def _apply_truck_mechanical(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.unexplained_hold = False
    truck.pre_stop_phase = truck.phase
    truck.phase = TruckPhase.STOPPED
    truck.speed_kmh = 0
    truck.comm_lost = False
    truck.mechanical_hold = True


def _apply_truck_stop_undefined(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.pre_stop_phase = truck.phase
    truck.unexplained_hold = True
    truck.phase = TruckPhase.STOPPED
    truck.speed_kmh = 0
    truck.mechanical_hold = False


def _apply_truck_engine_off(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.engine_off = True
    truck.pre_stop_phase = truck.phase
    truck.phase = TruckPhase.STOPPED
    truck.speed_kmh = 0


def _apply_truck_high_temp(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.high_engine_temp = True


def _apply_truck_low_oil(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.low_oil_pressure = True


def _apply_truck_battery_low(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.battery_low = True


def _apply_truck_fuel_rate_high(truck: TruckRuntime, params: dict, _world: SimulationWorld) -> None:
    truck.fuel_rate_factor = float(params.get("factor", 2.4))


def _apply_truck_tyre_pressure(truck: TruckRuntime, params: dict, _world: SimulationWorld) -> None:
    truck.tyre_pressure_low = True
    truck.tyre_fault_position = str(params.get("position", "FL"))


def _apply_truck_tyre_temp(truck: TruckRuntime, params: dict, _world: SimulationWorld) -> None:
    truck.tyre_temp_high = True
    truck.tyre_fault_position = str(params.get("position", "FL"))


def _apply_truck_sensor_loss(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.sensor_signal_loss = True


def _apply_truck_low_fuel(truck: TruckRuntime, params: dict, _world: SimulationWorld) -> None:
    pct = float(params.get("fuel_pct", 8.0))
    truck.fuel_pct = min(truck.fuel_pct, pct)


def _apply_truck_force_refuel(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.haul_dest_zone_code = truck.dest_zone_code
    truck.phase = TruckPhase.REFUELING
    truck.dest_zone_code = "FUEL"
    truck.road_progress = 0.0
    truck.speed_kmh = 0


def _apply_truck_maintenance(truck: TruckRuntime, _params: dict, _world: SimulationWorld) -> None:
    truck.in_maintenance = True
    truck.pre_stop_phase = truck.phase
    truck.phase = TruckPhase.STOPPED
    truck.speed_kmh = 0
    truck.mechanical_hold = False
    truck.unexplained_hold = False


def _apply_loader_breakdown(ldr: LoaderRuntime, _params: dict, world: SimulationWorld) -> None:
    ldr.mechanical_breakdown = True
    ldr.available = False
    ldr.capacity_factor = 0.0
    world.excavators_down.add(ldr.code)


def _apply_loader_reduced(ldr: LoaderRuntime, params: dict, world: SimulationWorld) -> None:
    factor = float(params.get("capacity_factor", 0.5))
    ldr.capacity_factor = factor
    ldr.mechanical_breakdown = False
    ldr.available = True
    world.excavators_down.discard(ldr.code)


def _apply_loader_slow(ldr: LoaderRuntime, params: dict, _world: SimulationWorld) -> None:
    ldr.slow_loading = True
    factor = float(params.get("capacity_factor", 0.3))
    ldr.capacity_factor = min(ldr.capacity_factor, factor)


def _apply_loader_comm_loss(ldr: LoaderRuntime, _params: dict, _world: SimulationWorld) -> None:
    ldr.communication_lost = True


def _apply_loader_maintenance(ldr: LoaderRuntime, _params: dict, world: SimulationWorld) -> None:
    ldr.in_maintenance = True
    ldr.mechanical_breakdown = True
    ldr.available = False
    ldr.capacity_factor = 0.0
    world.excavators_down.add(ldr.code)


def _apply_zone_close(zone: ZoneRuntime, _params: dict, _world: SimulationWorld) -> None:
    zone.closed = True
    zone.capacity = 0


def _apply_zone_reduce(zone: ZoneRuntime, params: dict, _world: SimulationWorld) -> None:
    cap = int(params.get("capacity", max(1, zone.base_capacity // 2)))
    zone.capacity = max(0, cap)
    zone.closed = False


def _apply_zone_pressure(zone: ZoneRuntime, params: dict, _world: SimulationWorld) -> None:
    zone.arrival_pressure = float(params.get("factor", 2.0))


def _apply_road_close(road: RoadRuntime, _params: dict, _world: SimulationWorld) -> None:
    road.closed = True


def _apply_road_speed(road: RoadRuntime, params: dict, _world: SimulationWorld) -> None:
    limit = float(params.get("speed_limit_kmh", road.base_speed_limit * 0.5))
    road.speed_limit = limit
    road.closed = False


def _apply_road_slow(road: RoadRuntime, params: dict, _world: SimulationWorld) -> None:
    road.slow_traffic_factor = float(params.get("factor", 0.5))


# ---------------------------------------------------------------------------
# Runtime restore effects (use original_state snapshot)
# ---------------------------------------------------------------------------


def _restore_truck(truck: TruckRuntime, orig: dict[str, Any], _world: SimulationWorld) -> None:
    truck.comm_lost = orig.get("comm_lost", False)
    truck.gps_lost = orig.get("gps_lost", False)
    truck.unexplained_hold = orig.get("unexplained_hold", False)
    truck.mechanical_hold = orig.get("mechanical_hold", False)
    truck.engine_off = orig.get("engine_off", False)
    truck.high_engine_temp = orig.get("high_engine_temp", False)
    truck.in_maintenance = orig.get("in_maintenance", False)
    truck.low_oil_pressure = orig.get("low_oil_pressure", False)
    truck.battery_low = orig.get("battery_low", False)
    truck.fuel_rate_factor = orig.get("fuel_rate_factor", 1.0)
    truck.sensor_signal_loss = orig.get("sensor_signal_loss", False)
    truck.comm_quality_drop = orig.get("comm_quality_drop", False)
    truck.tyre_pressure_low = orig.get("tyre_pressure_low", False)
    truck.tyre_temp_high = orig.get("tyre_temp_high", False)
    truck.tyre_fault_position = orig.get("tyre_fault_position")
    truck.active_oem_codes = set()
    truck.fuel_pct = orig.get("fuel_pct", truck.fuel_pct)
    pre = orig.get("pre_stop_phase")
    if pre:
        try:
            truck.phase = TruckPhase(pre)
        except ValueError:
            truck.phase = TruckPhase.WAITING_LOADING
    elif not truck.comm_lost:
        truck.phase = TruckPhase.WAITING_LOADING
    truck.pre_stop_phase = None
    truck.speed_kmh = orig.get("speed_kmh", 0)
    truck.phase_ticks_left = 5


def _restore_loader(ldr: LoaderRuntime, orig: dict[str, Any], world: SimulationWorld) -> None:
    ldr.available = orig.get("available", True)
    ldr.capacity_factor = orig.get("capacity_factor", 1.0)
    ldr.mechanical_breakdown = orig.get("mechanical_breakdown", False)
    ldr.communication_lost = orig.get("communication_lost", False)
    ldr.slow_loading = orig.get("slow_loading", False)
    ldr.in_maintenance = orig.get("in_maintenance", False)
    if ldr.mechanical_breakdown:
        world.excavators_down.add(ldr.code)
    else:
        world.excavators_down.discard(ldr.code)


def _restore_zone(zone: ZoneRuntime, orig: dict[str, Any], _world: SimulationWorld) -> None:
    zone.capacity = orig.get("capacity", zone.base_capacity)
    zone.closed = orig.get("closed", False)
    if hasattr(zone, "arrival_pressure"):
        zone.arrival_pressure = orig.get("arrival_pressure", 1.0)


def _restore_road(road: RoadRuntime, orig: dict[str, Any], _world: SimulationWorld) -> None:
    road.closed = orig.get("closed", False)
    road.speed_limit = orig.get("speed_limit", road.base_speed_limit)
    road.slow_traffic_factor = orig.get("slow_traffic_factor", 1.0)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

RUNTIME_APPLY: dict[str, Callable] = {
    "COMMUNICATION_LOSS_TRUCK": _apply_truck_comm_loss,
    "MECHANICAL_BREAKDOWN_TRUCK": _apply_truck_mechanical,
    "STOP_UNDEFINED": _apply_truck_stop_undefined,
    "ENGINE_OFF": _apply_truck_engine_off,
    "HIGH_ENGINE_TEMPERATURE": _apply_truck_high_temp,
    "LOW_OIL_PRESSURE": _apply_truck_low_oil,
    "BATTERY_VOLTAGE_LOW": _apply_truck_battery_low,
    "FUEL_RATE_HIGH": _apply_truck_fuel_rate_high,
    "TYRE_PRESSURE_LOW": _apply_truck_tyre_pressure,
    "TYRE_TEMPERATURE_HIGH": _apply_truck_tyre_temp,
    "SENSOR_SIGNAL_LOSS": _apply_truck_sensor_loss,
    "LOW_FUEL": _apply_truck_low_fuel,
    "FORCE_REFUEL": _apply_truck_force_refuel,
    "MAINTENANCE_TRUCK": _apply_truck_maintenance,
    "MECHANICAL_BREAKDOWN_LOADER": _apply_loader_breakdown,
    "REDUCED_CAPACITY": _apply_loader_reduced,
    "SLOW_LOADING": _apply_loader_slow,
    "COMMUNICATION_LOSS_LOADER": _apply_loader_comm_loss,
    "MAINTENANCE_LOADER": _apply_loader_maintenance,
    "CLOSE_ZONE": _apply_zone_close,
    "REDUCE_CAPACITY": _apply_zone_reduce,
    "INCREASE_ARRIVAL_PRESSURE": _apply_zone_pressure,
    "CLOSE_ROAD": _apply_road_close,
    "CHANGE_SPEED_LIMIT": _apply_road_speed,
    "SLOW_TRAFFIC": _apply_road_slow,
}

CAPTURE_FN: dict[str, Callable] = {
    "EQUIPMENT_TRUCK": capture_truck,
    "EQUIPMENT_LOADER": capture_loader,
    "ZONE": capture_zone,
    "ROAD": capture_road,
}

RESTORE_FN: dict[str, Callable] = {
    "EQUIPMENT_TRUCK": _restore_truck,
    "EQUIPMENT_LOADER": _restore_loader,
    "ZONE": _restore_zone,
    "ROAD": _restore_road,
}

ACTION_SPECS: dict[str, ActionSpec] = {}


def _reg(spec: ActionSpec) -> None:
    ACTION_SPECS[spec.action] = spec


_reg(ActionSpec("COMMUNICATION_LOSS", ("EQUIPMENT",), "COMMUNICATION_LOST", AlertSpec("COMM_LOSS", "{target} perte communication", "{target} — aucune télémétrie reçue.", AlertSeverity.WARNING)))
_reg(ActionSpec("MECHANICAL_BREAKDOWN", ("EQUIPMENT",), "MECHANICAL_FAILURE", AlertSpec("EQUIP_FAILURE", "{target} panne matérielle", "{target} — arrêt matériel critique.", AlertSeverity.CRITICAL)))
_reg(ActionSpec("STOP_UNDEFINED", ("EQUIPMENT",), "STOP_UNDEFINED", AlertSpec("STOP_UNDEFINED", "{target} arrêt non défini", "{target} arrêté — raison non confirmée.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("ENGINE_OFF", ("EQUIPMENT",), "ENGINE_OFF", AlertSpec("ENGINE_OFF", "{target} moteur arrêté", "{target} — moteur coupé.", AlertSeverity.INFO), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("HIGH_ENGINE_TEMPERATURE", ("EQUIPMENT",), "HIGH_ENGINE_TEMP", AlertSpec("HIGH_ENGINE_TEMP", "{target} surchauffe moteur", "{target} — température moteur élevée.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("LOW_OIL_PRESSURE", ("EQUIPMENT",), "LOW_OIL_PRESSURE", AlertSpec("LOW_OIL_PRESSURE", "{target} pression huile basse", "{target} — pression huile sous seuil de simulation.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("BATTERY_VOLTAGE_LOW", ("EQUIPMENT",), "BATTERY_VOLTAGE_LOW", AlertSpec("BATTERY_VOLTAGE_LOW", "{target} tension batterie basse", "{target} — tension batterie sous seuil de simulation.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("FUEL_RATE_HIGH", ("EQUIPMENT",), "FUEL_RATE_HIGH", AlertSpec("FUEL_RATE_HIGH", "{target} consommation anormale", "{target} — consommation carburant élevée (simulation).", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("TYRE_PRESSURE_LOW", ("EQUIPMENT",), "TYRE_PRESSURE_LOW", AlertSpec("TYRE_PRESSURE_LOW", "{target} pression pneu basse", "{target} — pression pneu hors plage de simulation.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("TYRE_TEMPERATURE_HIGH", ("EQUIPMENT",), "TYRE_TEMPERATURE_HIGH", AlertSpec("TYRE_TEMPERATURE_HIGH", "{target} température pneu élevée", "{target} — température pneu hors plage de simulation.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("SENSOR_SIGNAL_LOSS", ("EQUIPMENT",), "SENSOR_SIGNAL_LOSS", AlertSpec("SENSOR_SIGNAL_LOSS", "{target} perte signal capteur", "{target} — télémétrie capteur interrompue.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("LOW_FUEL", ("EQUIPMENT",), "LOW_FUEL", AlertSpec("LOW_FUEL", "{target} carburant bas", "{target} — niveau carburant critique.", AlertSeverity.WARNING), equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("FORCE_REFUEL", ("EQUIPMENT",), "FORCE_REFUEL", None, equipment_subtype="HAUL_TRUCK"))
_reg(ActionSpec("MAINTENANCE", ("EQUIPMENT",), "MAINTENANCE_START", AlertSpec("MAINTENANCE", "{target} maintenance", "{target} — entrée en maintenance.", AlertSeverity.INFO)))
_reg(ActionSpec("REDUCED_CAPACITY", ("EQUIPMENT",), "CAPACITY_REDUCED", AlertSpec("CAPACITY_REDUCED", "{target} capacité réduite", "{target} — capacité de chargement réduite.", AlertSeverity.INFO), equipment_subtype="LOADER"))
_reg(ActionSpec("SLOW_LOADING", ("EQUIPMENT",), "SLOW_LOADING", AlertSpec("SLOW_LOADING", "{target} chargement lent", "{target} — temps de chargement augmenté.", AlertSeverity.INFO), equipment_subtype="LOADER"))
_reg(ActionSpec("CLOSE_ZONE", ("ZONE",), "ZONE_CLOSED", AlertSpec("ZONE_CLOSED", "Zone {target} fermée", "Zone {target} — accès interdit.", AlertSeverity.WARNING)))
_reg(ActionSpec("REDUCE_CAPACITY", ("ZONE",), "ZONE_CAPACITY_REDUCED", AlertSpec("CAPACITY_REDUCED", "Zone {target} capacité réduite", "Zone {target} — capacité réduite.", AlertSeverity.INFO)))
_reg(ActionSpec("INCREASE_ARRIVAL_PRESSURE", ("ZONE",), "ZONE_PRESSURE", None))
_reg(ActionSpec("CLOSE_ROAD", ("ROAD",), "ROAD_CLOSED", AlertSpec("ROAD_CLOSED", "Route {target} fermée", "Route {target} — circulation interdite.", AlertSeverity.INFO)))
_reg(ActionSpec("CHANGE_SPEED_LIMIT", ("ROAD",), "ROAD_SPEED_LIMIT", AlertSpec("ROAD_RESTRICTED", "Route {target} limitée", "Route {target} — limitation de vitesse.", AlertSeverity.INFO)))
_reg(ActionSpec("SLOW_TRAFFIC", ("ROAD",), "SLOW_TRAFFIC", AlertSpec("SLOW_TRAFFIC", "Route {target} trafic lent", "Route {target} — circulation ralentie.", AlertSeverity.INFO)))


def equipment_kind(code: str) -> str:
    if code.startswith("TRK"):
        return "TRUCK"
    if code.startswith("EXC") or code.startswith("LDR"):
        return "LOADER"
    return "UNKNOWN"


def runtime_key(action: str, target_type: str, target_id: str) -> str:
    action = canonical_action(action)
    if action == "MECHANICAL_BREAKDOWN":
        return "MECHANICAL_BREAKDOWN_TRUCK" if equipment_kind(target_id) == "TRUCK" else "MECHANICAL_BREAKDOWN_LOADER"
    if action == "COMMUNICATION_LOSS":
        return "COMMUNICATION_LOSS_TRUCK" if equipment_kind(target_id) == "TRUCK" else "COMMUNICATION_LOSS_LOADER"
    if action == "MAINTENANCE":
        return "MAINTENANCE_TRUCK" if equipment_kind(target_id) == "TRUCK" else "MAINTENANCE_LOADER"
    return action


def capture_key(target_type: str, target_id: str) -> str:
    if target_type == "EQUIPMENT":
        return "EQUIPMENT_TRUCK" if equipment_kind(target_id) == "TRUCK" else "EQUIPMENT_LOADER"
    return target_type


def get_spec(action: str) -> ActionSpec | None:
    return ACTION_SPECS.get(canonical_action(action))


def apply_runtime(
    world: SimulationWorld,
    target_type: str,
    target_id: str,
    action: str,
    parameters: dict,
) -> dict[str, Any]:
    """Apply runtime mutation; returns original_state snapshot."""
    action = canonical_action(action)
    if action == "RESTORE":
        return {}

    ck = capture_key(target_type, target_id)
    capture_fn = CAPTURE_FN.get(ck)
    if not capture_fn:
        raise ValueError(f"No capture for {target_type}/{target_id}")

    if target_type == "EQUIPMENT":
        if equipment_kind(target_id) == "TRUCK":
            entity = world.trucks.get(target_id)
        else:
            entity = world.loaders.get(target_id)
    elif target_type == "ZONE":
        entity = world.zones.get(target_id)
    elif target_type == "ROAD":
        entity = _find_road(world, target_id)
    else:
        raise ValueError(f"Unknown target_type {target_type}")

    if not entity:
        raise ValueError(f"Target {target_id} not found")

    orig = capture_fn(entity)
    rk = runtime_key(action, target_type, target_id)
    apply_fn = RUNTIME_APPLY.get(rk)
    if not apply_fn:
        raise ValueError(f"Unsupported action {action} for {target_type}/{target_id}")
    apply_fn(entity, parameters, world)
    return orig


def restore_runtime(
    world: SimulationWorld,
    target_type: str,
    target_id: str,
    original_state: dict[str, Any],
) -> None:
    ck = capture_key(target_type, target_id)
    restore_fn = RESTORE_FN.get(ck)
    if not restore_fn:
        return
    if target_type == "EQUIPMENT":
        if equipment_kind(target_id) == "TRUCK":
            entity = world.trucks.get(target_id)
        else:
            entity = world.loaders.get(target_id)
    elif target_type == "ZONE":
        entity = world.zones.get(target_id)
    elif target_type == "ROAD":
        entity = _find_road(world, target_id)
    else:
        return
    if entity:
        restore_fn(entity, original_state, world)


def _find_road(world: SimulationWorld, code: str) -> RoadRuntime | None:
    road = world.roads.get(code)
    if road:
        return road
    for r in world.roads.values():
        if r.code == code:
            return r
    return None
