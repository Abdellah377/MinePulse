"""Per-tire pressure / temperature stream for haul trucks."""

from __future__ import annotations

from decimal import Decimal

from app.oem.catalog import TYRE_POSITIONS
from simulator.state_machine import TruckRuntime

NOMINAL_PRESSURE = 700.0
NOMINAL_TEMP = 42.0


def ensure_tyres(truck: TruckRuntime) -> None:
    if truck.tyres:
        return
    for pos in TYRE_POSITIONS:
        truck.tyres[pos] = {
            "pressure_kpa": NOMINAL_PRESSURE + truck.rng.uniform(-18, 18),
            "temperature_c": NOMINAL_TEMP + truck.rng.uniform(-4, 4),
        }


def step_tyres(truck: TruckRuntime) -> None:
    ensure_tyres(truck)
    moving = truck.is_moving() and truck.speed_kmh > 2
    load = truck.payload_t > 50
    for pos, tyre in truck.tyres.items():
        p_target = NOMINAL_PRESSURE + (12 if load else 0)
        t_target = NOMINAL_TEMP + (14 if moving else 0) + (8 if load else 0)
        if pos == truck.tyre_fault_position:
            if truck.tyre_pressure_low:
                p_target = 400.0
            if truck.tyre_temp_high:
                t_target = 92.0
            if truck.scenario_tyre_pressure_target is not None:
                p_target = truck.scenario_tyre_pressure_target
            if truck.scenario_tyre_temp_target is not None:
                t_target = truck.scenario_tyre_temp_target
        pressure_response = 0.25 if truck.scenario_tyre_pressure_target is not None else 0.08
        temperature_response = 0.18 if truck.scenario_tyre_temp_target is not None else 0.06
        tyre["pressure_kpa"] += (p_target - tyre["pressure_kpa"]) * pressure_response + truck.rng.uniform(-1.2, 1.2)
        tyre["temperature_c"] += (t_target - tyre["temperature_c"]) * temperature_response + truck.rng.uniform(-0.4, 0.4)
        tyre["pressure_kpa"] = max(250.0, min(950.0, tyre["pressure_kpa"]))
        tyre["temperature_c"] = max(15.0, min(120.0, tyre["temperature_c"]))


def tyre_rows(truck: TruckRuntime) -> list[dict]:
    ensure_tyres(truck)
    step_tyres(truck)
    rows = []
    for pos, tyre in truck.tyres.items():
        rows.append(
            {
                "position": pos,
                "pressure_kpa": Decimal(str(round(tyre["pressure_kpa"], 1))),
                "temperature_c": Decimal(str(round(tyre["temperature_c"], 1))),
            }
        )
    return rows
