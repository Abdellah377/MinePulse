"""OEM sensor catalog — single source of labels, units, and type availability."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.oem.thresholds import SIM_THRESHOLDS


@dataclass(frozen=True)
class SensorDefinition:
    key: str
    label_fr: str
    unit: str
    category: str
    source: str
    chart_type: str
    precision: int
    available_for: tuple[str, ...]


TRUCK = ("HAUL_TRUCK",)
MOTORIZED = ("HAUL_TRUCK", "EXCAVATOR", "LOADER", "DOZER", "GRADER", "DRILL")

SENSORS: dict[str, SensorDefinition] = {
    "speed_kmh": SensorDefinition("speed_kmh", "Vitesse", "km/h", "mouvement", "telemetry", "line", 1, TRUCK),
    "fuel_level_pct": SensorDefinition(
        "fuel_level_pct", "Niveau carburant", "%", "carburant", "telemetry", "line", 1, MOTORIZED
    ),
    "fuel_rate_lph": SensorDefinition("fuel_rate_lph", "Consommation", "l/h", "carburant", "telemetry", "line", 2, TRUCK),
    "payload_t": SensorDefinition("payload_t", "Charge utile", "t", "payload", "telemetry", "line", 1, TRUCK),
    "engine_rpm": SensorDefinition("engine_rpm", "Régime", "tr/min", "moteur", "telemetry", "line", 0, MOTORIZED),
    "engine_load_pct": SensorDefinition(
        "engine_load_pct", "Charge moteur", "%", "moteur", "telemetry", "line", 1, MOTORIZED
    ),
    "engine_temp_c": SensorDefinition(
        "engine_temp_c", "Température moteur", "°C", "température", "telemetry", "line", 1, MOTORIZED
    ),
    "coolant_temp_c": SensorDefinition(
        "coolant_temp_c", "Température liquide", "°C", "température", "telemetry", "line", 1, MOTORIZED
    ),
    "oil_pressure_kpa": SensorDefinition(
        "oil_pressure_kpa", "Pression huile", "kPa", "pression", "telemetry", "line", 1, MOTORIZED
    ),
    "battery_voltage": SensorDefinition(
        "battery_voltage", "Tension batterie", "V", "électrique", "telemetry", "line", 2, MOTORIZED
    ),
    "communication_quality": SensorDefinition(
        "communication_quality", "Qualité communication", "%", "communication", "telemetry", "line", 0, MOTORIZED
    ),
    "engine_hours": SensorDefinition("engine_hours", "Heures moteur", "h", "moteur", "telemetry", "line", 2, MOTORIZED),
    "odometer_km": SensorDefinition("odometer_km", "Odomètre", "km", "mouvement", "telemetry", "line", 1, TRUCK),
    "tyre_pressure_kpa": SensorDefinition(
        "tyre_pressure_kpa", "Pression pneu", "kPa", "pneus", "tyre_telemetry", "line", 1, TRUCK
    ),
    "tyre_temp_c": SensorDefinition(
        "tyre_temp_c", "Température pneu", "°C", "pneus", "tyre_telemetry", "line", 1, TRUCK
    ),
}

TELEMETRY_COLUMNS = {k for k, s in SENSORS.items() if s.source == "telemetry"}

TYRE_POSITIONS: dict[str, str] = {
    "FL": "Avant gauche",
    "FR": "Avant droite",
    "R1L": "Arrière 1 gauche",
    "R1R": "Arrière 1 droite",
    "R2L": "Arrière 2 gauche",
    "R2R": "Arrière 2 droite",
}

CATEGORY_LABELS = {
    "moteur": "Moteur",
    "carburant": "Carburant",
    "température": "Température",
    "pression": "Pression",
    "électrique": "Électrique",
    "communication": "Communication",
    "payload": "Charge",
    "pneus": "Pneus",
    "mouvement": "Mouvement",
}

SIM_ERROR_CODES = {
    "SIM-ENG-TEMP-HIGH": {"category": "moteur", "severity": "WARNING", "label": "Température moteur élevée"},
    "SIM-OIL-PRESS-LOW": {"category": "pression", "severity": "WARNING", "label": "Pression huile basse"},
    "SIM-BATT-VOLT-LOW": {"category": "électrique", "severity": "WARNING", "label": "Tension batterie basse"},
    "SIM-FUEL-RATE-HIGH": {"category": "carburant", "severity": "WARNING", "label": "Consommation carburant anormale"},
    "SIM-COMM-LOSS": {"category": "communication", "severity": "WARNING", "label": "Perte communication"},
    "SIM-COMM-QUALITY-LOW": {"category": "communication", "severity": "INFO", "label": "Qualité communication faible"},
    "SIM-TYRE-PRESS-LOW": {"category": "pneus", "severity": "WARNING", "label": "Pression pneu hors plage"},
    "SIM-TYRE-TEMP-HIGH": {"category": "pneus", "severity": "WARNING", "label": "Température pneu élevée"},
    "SIM-SENSOR-LOSS": {"category": "communication", "severity": "WARNING", "label": "Perte signal capteur"},
    "SIM-SENSOR-ANOMALY": {"category": "moteur", "severity": "WARNING", "label": "Anomalie capteur"},
}

EVENT_TYPE_TO_CODE = {
    "COMMUNICATION_LOST": "SIM-COMM-LOSS",
    "HIGH_ENGINE_TEMP": "SIM-ENG-TEMP-HIGH",
    "LOW_OIL_PRESSURE": "SIM-OIL-PRESS-LOW",
    "BATTERY_VOLTAGE_LOW": "SIM-BATT-VOLT-LOW",
    "FUEL_RATE_HIGH": "SIM-FUEL-RATE-HIGH",
    "TYRE_PRESSURE_LOW": "SIM-TYRE-PRESS-LOW",
    "TYRE_TEMPERATURE_HIGH": "SIM-TYRE-TEMP-HIGH",
    "SENSOR_SIGNAL_LOSS": "SIM-SENSOR-LOSS",
    "SIM-SENSOR-ANOMALY": "SIM-SENSOR-ANOMALY",
    "SIM-ENG-TEMP-HIGH": "SIM-ENG-TEMP-HIGH",
    "SIM-OIL-PRESS-LOW": "SIM-OIL-PRESS-LOW",
    "SIM-BATT-VOLT-LOW": "SIM-BATT-VOLT-LOW",
    "SIM-FUEL-RATE-HIGH": "SIM-FUEL-RATE-HIGH",
    "SIM-COMM-LOSS": "SIM-COMM-LOSS",
    "SIM-TYRE-PRESS-LOW": "SIM-TYRE-PRESS-LOW",
    "SIM-TYRE-TEMP-HIGH": "SIM-TYRE-TEMP-HIGH",
    "SIM-SENSOR-LOSS": "SIM-SENSOR-LOSS",
}


def catalog_payload() -> dict:
    sensors = []
    for s in SENSORS.values():
        row = asdict(s)
        row["available_for"] = list(s.available_for)
        th = SIM_THRESHOLDS.get(s.key)
        row["threshold"] = (
            {
                "warnLow": th.warn_low,
                "warnHigh": th.warn_high,
                "critLow": th.crit_low,
                "critHigh": th.crit_high,
                "source": th.source,
            }
            if th
            else None
        )
        sensors.append(row)
    return {
        "sensors": sensors,
        "categories": CATEGORY_LABELS,
        "tyrePositions": [{"code": k, "labelFr": v} for k, v in TYRE_POSITIONS.items()],
        "errorCodes": [
            {"code": k, **v, "source": "simulation"} for k, v in SIM_ERROR_CODES.items()
        ],
        "thresholdSource": "simulation/test",
    }


def sensors_for_type(equipment_type: str) -> list[SensorDefinition]:
    return [s for s in SENSORS.values() if equipment_type in s.available_for]


def is_available(key: str, equipment_type: str) -> bool:
    s = SENSORS.get(key)
    return bool(s and equipment_type in s.available_for)
