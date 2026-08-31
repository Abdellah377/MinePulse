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
        "ai_recommendation_decisions",
        "ai_recommendation_discussion_messages",
        "ai_optimization_runs",
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

# Incremental columns whose absence lets the API start but causes runtime ORM
# failures. Keep this deliberately small; the SQL dump remains the full schema
# source of truth.
EXPECTED_COLUMNS = {
    "alerts": frozenset({"site_id", "occurred_at"}),
    "ai_investigations": frozenset({"debug_trace"}),
}
