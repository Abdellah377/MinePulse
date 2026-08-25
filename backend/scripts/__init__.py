"""Database connection and schema verification scripts."""

EXPECTED_TABLES = frozenset(
    {
        "sites",
        "shifts",
        "operators",
        "materials",
        "equipment",
        "zones",
        "haul_roads",
        "equipment_assignments",
        "equipment_positions",
        "equipment_telemetry",
        "equipment_states",
        "cycles",
        "cycle_stages",
        "trips",
        "fuel_events",
        "maintenance_events",
        "downtime_events",
        "production_targets",
        "production_actuals",
        "system_events",
        "alerts",
        "predictions",
        "ai_recommendations",
        "ai_investigations",
        "tyre_telemetry",
        "operational_settings",
    }
)

EXPECTED_ENUMS = frozenset(
    {
        "equipment_type",
        "equipment_state",
        "zone_type",
        "alert_severity",
        "alert_status",
        "alert_source",
        "recommendation_status",
    }
)
