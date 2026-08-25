"""DB enum ↔ frontend vocabulary mapping."""

from app.db.enums import AlertSeverity, AlertSource, AlertStatus, EquipmentState, EquipmentType, ZoneType

EQUIPMENT_TYPE_TO_UI: dict[EquipmentType, str] = {
    EquipmentType.HAUL_TRUCK: "haul_truck",
    EquipmentType.EXCAVATOR: "excavator",
    EquipmentType.LOADER: "loader",
    EquipmentType.DOZER: "dozer",
    EquipmentType.GRADER: "grader",
    EquipmentType.DRILL: "drill",
    EquipmentType.WATER_TRUCK: "water_truck",
    EquipmentType.LIGHT_VEHICLE: "light_vehicle",
    EquipmentType.OTHER: "other",
}

EQUIPMENT_STATE_TO_UI: dict[EquipmentState, str] = {
    EquipmentState.MOVING_LOADED: "mouvement_charge",
    EquipmentState.MOVING_EMPTY: "mouvement_vide",
    EquipmentState.WAITING_LOADING: "attente_charge",
    EquipmentState.LOADING: "chargement",
    EquipmentState.WAITING_DUMPING: "attente_dechargement",
    EquipmentState.DUMPING: "dechargement",
    EquipmentState.STOPPED_OPERATIONAL: "arret_exploitation",
    EquipmentState.STOPPED_MECHANICAL: "arret_materiel",
    EquipmentState.STOPPED_EXTERNAL: "arret_exterieur",
    EquipmentState.STOPPED_UNDEFINED: "arret_indetermine",
    EquipmentState.REFUELING: "ravitaillement",
    EquipmentState.MAINTENANCE: "arret_materiel",
    EquipmentState.PARKED: "parking",
    EquipmentState.ENGINE_OFF: "eteint",
    EquipmentState.NO_DATA: "aucune_donnee",
    EquipmentState.UNKNOWN: "indetermine",
}

ZONE_TYPE_TO_UI: dict[ZoneType, str] = {
    ZoneType.LOADING_BENCH: "chargement",
    ZoneType.DUMP_AREA: "dechargement",
    ZoneType.CRUSHER: "concasseur",
    ZoneType.FUEL_STATION: "fuel",
    ZoneType.MAINTENANCE_WORKSHOP: "atelier",
    ZoneType.PARKING: "parking",
    ZoneType.RESTRICTED_AREA: "restreinte",
    ZoneType.STOCKPILE: "dechargement",
    ZoneType.SHIFT_CHANGE_AREA: "parking",
    ZoneType.OTHER: "restreinte",
}

ALERT_SEVERITY_TO_UI: dict[AlertSeverity, str] = {
    AlertSeverity.INFO: "info",
    AlertSeverity.WARNING: "warning",
    AlertSeverity.CRITICAL: "critical",
}

ALERT_STATUS_TO_UI: dict[AlertStatus, str] = {
    AlertStatus.NEW: "new",
    AlertStatus.ACKNOWLEDGED: "acknowledged",
    AlertStatus.INVESTIGATING: "investigating",
    AlertStatus.ASSIGNED: "assigned",
    AlertStatus.RESOLVED: "resolved",
}
