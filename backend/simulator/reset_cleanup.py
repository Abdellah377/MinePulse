"""Site-scoped persisted-data cleanup for a fresh simulator run."""

from __future__ import annotations

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.ai.contracts import TriggerSource
from app.db.enums import AlertSource, EquipmentState, EquipmentType
from app.db.models import (
    AiInvestigation,
    AiRecommendation,
    Alert,
    Cycle,
    CycleStage,
    DowntimeEvent,
    Equipment,
    EquipmentAssignment,
    EquipmentPosition,
    EquipmentTelemetry,
    FuelEvent,
    MaintenanceEvent,
    ProductionActual,
    Shift,
    Site,
    SystemEvent,
    Trip,
    TyreTelemetry,
    Zone,
)
from app.db.models.telemetry import EquipmentState as EquipmentStateRow


def _execute_delete(session: Session, model, where_clause) -> int:
    result = session.execute(delete(model).where(where_clause))
    return int(result.rowcount or 0)


def clear_simulation_run_data(session: Session, *, site_code: str = "MP-SIM-01") -> dict[str, int]:
    """Delete only dynamic records belonging to the configured simulation site.

    Reference configuration, non-simulation sites, non-monitoring RULE alerts,
    unrelated predictions, and unrelated/human AI records are deliberately preserved.
    """
    site = session.scalar(select(Site).where(Site.code == site_code))
    if site is None:
        raise RuntimeError(f"Simulation site not found: {site_code}")

    equipment_ids = select(Equipment.equipment_id).where(Equipment.site_id == site.site_id)
    zone_ids = select(Zone.zone_id).where(Zone.site_id == site.site_id)
    shift_ids = select(Shift.shift_id).where(Shift.site_id == site.site_id)
    cycle_ids = select(Cycle.cycle_id).where(Cycle.truck_id.in_(equipment_ids))

    alert_scope = or_(
        Alert.site_id == site.site_id,
        Alert.equipment_id.in_(equipment_ids),
        Alert.zone_id.in_(zone_ids),
    )
    resettable_alerts = alert_scope & or_(
        Alert.source == AlertSource.FMS,
        (Alert.source == AlertSource.RULE) & Alert.metadata_.has_key("monitoring"),  # noqa: W601
        (Alert.source == AlertSource.PREDICTION)
        & (Alert.metadata_["monitoring"]["source"].as_string() == "FAILURE_RISK_V1"),
    )
    alert_ids = list(session.scalars(select(Alert.alert_id).where(resettable_alerts)).all())
    source_record_ids = [f"alert-{alert_id}" for alert_id in alert_ids]

    investigation_scope = (
        (AiInvestigation.site_id == site.site_id)
        & (AiInvestigation.trigger_source == TriggerSource.AUTOMATIC_MONITORING.value)
    )
    if source_record_ids:
        investigation_scope = or_(
            investigation_scope,
            (AiInvestigation.site_id == site.site_id)
            & AiInvestigation.trigger_data["source_record_id"].as_string().in_(source_record_ids),
        )

    counts: dict[str, int] = {}
    counts["ai_investigations"] = _execute_delete(session, AiInvestigation, investigation_scope)
    if alert_ids:
        counts["ai_recommendations"] = _execute_delete(
            session,
            AiRecommendation,
            AiRecommendation.trigger_id.in_(alert_ids)
            & AiRecommendation.trigger_type.in_(("ALERT", "EXISTING_ALERT", "OPERATIONAL_ALERT")),
        )
        counts["alerts"] = _execute_delete(session, Alert, Alert.alert_id.in_(alert_ids))
    else:
        counts["ai_recommendations"] = 0
        counts["alerts"] = 0

    # Child-before-parent order keeps cleanup valid even when deployments use
    # stricter foreign keys than the current development schema.
    counts["production_actuals"] = _execute_delete(
        session, ProductionActual, ProductionActual.shift_id.in_(shift_ids)
    )
    counts["cycle_stages"] = _execute_delete(
        session, CycleStage, CycleStage.cycle_id.in_(cycle_ids)
    )
    counts["trips"] = _execute_delete(
        session,
        Trip,
        or_(Trip.truck_id.in_(equipment_ids), Trip.shift_id.in_(shift_ids)),
    )
    counts["equipment_assignments"] = _execute_delete(
        session,
        EquipmentAssignment,
        or_(
            EquipmentAssignment.truck_id.in_(equipment_ids),
            EquipmentAssignment.loader_id.in_(equipment_ids),
            EquipmentAssignment.shift_id.in_(shift_ids),
            EquipmentAssignment.origin_zone_id.in_(zone_ids),
            EquipmentAssignment.destination_zone_id.in_(zone_ids),
        ),
    )
    counts["cycles"] = _execute_delete(session, Cycle, Cycle.truck_id.in_(equipment_ids))
    for name, model in (
        ("equipment_states", EquipmentStateRow),
        ("equipment_telemetry", EquipmentTelemetry),
        ("tyre_telemetry", TyreTelemetry),
        ("equipment_positions", EquipmentPosition),
        ("fuel_events", FuelEvent),
        ("maintenance_events", MaintenanceEvent),
        ("downtime_events", DowntimeEvent),
    ):
        counts[name] = _execute_delete(session, model, model.equipment_id.in_(equipment_ids))
    system_event_scope = or_(
        SystemEvent.equipment_id.in_(equipment_ids),
        SystemEvent.zone_id.in_(zone_ids),
    )
    # Legacy zone/road simulator events lacked entity scope. Only the canonical
    # simulator reset may use their explicit FMS_SIM source marker.
    if site.code == "MP-SIM-01":
        system_event_scope = or_(system_event_scope, SystemEvent.source_system == "FMS_SIM")
    counts["system_events"] = _execute_delete(session, SystemEvent, system_event_scope)

    session.execute(
        update(Equipment)
        .where(Equipment.site_id == site.site_id)
        .values(
            current_state=EquipmentState.PARKED
        )
    )
    # Non-truck equipment retains the simulator's established reset state.
    session.execute(
        update(Equipment)
        .where(Equipment.site_id == site.site_id, Equipment.type != EquipmentType.HAUL_TRUCK)
        .values(current_state=EquipmentState.STOPPED_OPERATIONAL)
    )
    return counts
