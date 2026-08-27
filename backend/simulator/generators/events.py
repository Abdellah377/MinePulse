from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alert, SystemEvent
from app.db.enums import AlertSeverity, AlertSource, AlertStatus


def emit_system_event(
    session: Session,
    ts,
    event_type: str,
    equipment_id: int | None,
    message: str,
    raw_data: dict | None = None,
) -> None:
    session.add(
        SystemEvent(
            equipment_id=equipment_id,
            ts=ts,
            event_type=event_type,
            source_system="FMS_SIM",
            message=message,
            raw_data=raw_data or {},
        )
    )


def emit_fms_alert(
    session: Session,
    ts,
    alert_type: str,
    title: str,
    description: str,
    equipment_id: int | None,
    zone_id: int | None = None,
    severity: AlertSeverity = AlertSeverity.WARNING,
) -> Alert:
    alert = Alert(
        created_at=datetime.now(timezone.utc),
        occurred_at=ts,
        source=AlertSource.FMS,
        severity=severity,
        status=AlertStatus.NEW,
        alert_type=alert_type,
        title=title,
        description=description,
        equipment_id=equipment_id,
        zone_id=zone_id,
    )
    session.add(alert)
    session.flush()
    return alert


def resolve_fms_alert(
    session: Session,
    ts,
    alert_type: str,
    *,
    equipment_id: int | None = None,
    zone_id: int | None = None,
) -> int:
    """Resolve open FMS alerts matching type and target. Returns count resolved."""
    q = select(Alert).where(
        Alert.source == AlertSource.FMS,
        Alert.alert_type == alert_type,
        Alert.status.in_((AlertStatus.NEW, AlertStatus.ACKNOWLEDGED, AlertStatus.INVESTIGATING, AlertStatus.ASSIGNED)),
    )
    if equipment_id is not None:
        q = q.where(Alert.equipment_id == equipment_id)
    if zone_id is not None:
        q = q.where(Alert.zone_id == zone_id)
    rows = session.scalars(q).all()
    for alert in rows:
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = ts
    session.flush()
    return len(rows)
