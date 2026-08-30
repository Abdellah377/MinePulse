"""State-dependent telemetry — reject impossible combinations."""

from __future__ import annotations

from decimal import Decimal

from simulator.state_machine import TruckPhase, TruckRuntime


def build_telemetry(truck: TruckRuntime) -> dict:
    if truck.phase == TruckPhase.NO_COMM or truck.comm_lost:
        return {}
    if truck.sensor_signal_loss:
        return {}

    phase = truck.phase
    moving = phase in (TruckPhase.MOVING_LOADED, TruckPhase.MOVING_EMPTY)
    refueling_travel = phase == TruckPhase.REFUELING and truck.road_progress < 1.0
    is_moving = moving or refueling_travel

    speed = truck.speed_kmh if is_moving else 0.0
    if is_moving and speed <= 0:
        speed = max(5.0, truck.speed_kmh)

    if phase == TruckPhase.MOVING_LOADED:
        payload = max(truck.payload_t, 50.0)
        rpm = 1700 + min(300, speed * 5)
        load_pct = min(100, 55 + payload / 4)
        fuel_rate = 18 + speed * 0.35
        engine_on = True
    elif phase == TruckPhase.MOVING_EMPTY:
        payload = min(truck.payload_t, 5.0)
        rpm = 1500 + min(250, speed * 4)
        load_pct = 20 + speed * 0.3
        fuel_rate = 8 + speed * 0.25
        engine_on = True
    elif phase == TruckPhase.WAITING_LOADING:
        payload = min(truck.payload_t, 5.0)
        rpm = 750
        load_pct = 8
        fuel_rate = 2.5
        engine_on = True
        speed = 0.0
    elif phase == TruckPhase.LOADING:
        payload = truck.payload_t
        rpm = 900
        load_pct = 25 + payload / 5
        fuel_rate = 4.0
        engine_on = True
        speed = 0.0
    elif phase == TruckPhase.WAITING_DUMPING:
        payload = max(truck.payload_t, 50.0)
        rpm = 750
        load_pct = 15
        fuel_rate = 2.5
        engine_on = True
        speed = 0.0
    elif phase == TruckPhase.DUMPING:
        payload = truck.payload_t
        rpm = 850
        load_pct = 20
        fuel_rate = 3.5
        engine_on = True
        speed = 0.0
    elif phase == TruckPhase.REFUELING:
        payload = truck.payload_t
        if refueling_travel:
            rpm = 1400
            load_pct = 18
            fuel_rate = 6 + speed * 0.2
            engine_on = True
        else:
            rpm = 700
            load_pct = 5
            fuel_rate = 1.5
            engine_on = True
            speed = 0.0
    elif phase == TruckPhase.STOPPED:
        payload = truck.payload_t
        rpm = 0
        load_pct = 0
        fuel_rate = 0.0
        engine_on = False
        speed = 0.0
    else:
        payload = truck.payload_t
        rpm = 750
        load_pct = 10
        fuel_rate = 2.0
        engine_on = True
        speed = 0.0

    truck.speed_kmh = speed
    fuel_rate *= truck.fuel_rate_factor

    # Thermal / electrical physics (sim time already advanced in advance_phase)
    jitter = truck.rng.uniform(-0.4, 0.4)
    if engine_on:
        target_temp = 82.0 + load_pct * 0.18 + (8.0 if is_moving else 0.0)
        if truck.high_engine_temp:
            target_temp = max(target_temp, 108.0)
        if truck.scenario_engine_temp_target is not None:
            target_temp = max(target_temp, truck.scenario_engine_temp_target)
        if truck.scenario_engine_temp_ceiling is not None:
            target_temp = min(target_temp, truck.scenario_engine_temp_ceiling)
        truck.engine_temp_c += (target_temp - truck.engine_temp_c) * 0.12 + jitter
        coolant_target = target_temp - 6.0
        if truck.scenario_coolant_temp_target is not None:
            coolant_target = max(coolant_target, truck.scenario_coolant_temp_target)
        truck.coolant_temp_c += (coolant_target - truck.coolant_temp_c) * 0.1 + jitter * 0.5
        oil_target = 380.0 if truck.low_oil_pressure else 420.0 + load_pct * 0.8
        if truck.low_oil_pressure:
            oil_target = 140.0
        if truck.scenario_oil_pressure_target is not None:
            oil_target = min(oil_target, truck.scenario_oil_pressure_target)
        truck.oil_pressure_kpa += (oil_target - truck.oil_pressure_kpa) * 0.2
        batt_target = 23.0 if truck.battery_low else 27.4
        if truck.scenario_battery_voltage_target is not None:
            batt_target = min(batt_target, truck.scenario_battery_voltage_target)
        truck.battery_voltage += (batt_target - truck.battery_voltage) * 0.15
        comm_target = 94.0 + truck.rng.uniform(-3, 3)
        if truck.scenario_comm_quality_target is not None:
            comm_target = min(comm_target, truck.scenario_comm_quality_target)
        truck.communication_quality += (comm_target - truck.communication_quality) * 0.35
        truck.communication_quality = max(0.0, min(99.0, truck.communication_quality))
    else:
        truck.engine_temp_c += (28.0 - truck.engine_temp_c) * 0.04
        truck.coolant_temp_c += (24.0 - truck.coolant_temp_c) * 0.04
        truck.oil_pressure_kpa += (40.0 - truck.oil_pressure_kpa) * 0.25
        batt_target = 22.0 if truck.battery_low else 25.6
        truck.battery_voltage += (batt_target - truck.battery_voltage) * 0.08
        truck.communication_quality = max(50.0, min(99.0, 90.0 + truck.rng.uniform(-4, 2)))

    if truck.comm_quality_drop:
        truck.communication_quality = min(truck.communication_quality, 35.0)

    return {
        "speed_kmh": Decimal(str(round(speed, 1))),
        "engine_rpm": Decimal(str(round(rpm, 0))),
        "engine_load_pct": Decimal(str(round(load_pct, 1))),
        "fuel_level_pct": Decimal(str(round(truck.fuel_pct, 1))),
        "fuel_rate_lph": Decimal(str(round(fuel_rate, 2))),
        "engine_temp_c": Decimal(str(round(truck.engine_temp_c, 1))),
        "coolant_temp_c": Decimal(str(round(truck.coolant_temp_c, 1))),
        "oil_pressure_kpa": Decimal(str(round(max(0.0, truck.oil_pressure_kpa), 1))),
        "payload_t": Decimal(str(round(payload, 1))),
        "engine_hours": Decimal(str(round(truck.engine_hours, 2))),
        "odometer_km": Decimal(str(round(truck.odometer_km, 2))),
        "battery_voltage": Decimal(str(round(truck.battery_voltage, 2))),
        "communication_quality": Decimal(str(round(truck.communication_quality, 0))),
    }
