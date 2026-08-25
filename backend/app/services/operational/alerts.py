"""Alert mutations with validated state transitions."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.enums import AlertStatus
from app.db.models import Alert, Equipment, Operator, Zone

_ALLOWED: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.NEW: {AlertStatus.ACKNOWLEDGED, AlertStatus.INVESTIGATING, AlertStatus.ASSIGNED, AlertStatus.RESOLVED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.INVESTIGATING, AlertStatus.ASSIGNED, AlertStatus.RESOLVED},
    AlertStatus.INVESTIGATING: {AlertStatus.ASSIGNED, AlertStatus.RESOLVED},
    AlertStatus.ASSIGNED: {AlertStatus.RESOLVED, AlertStatus.INVESTIGATING},
    AlertStatus.RESOLVED: set(),
}


def _parse_alert_pk(alert_id: str) -> int:
    raw = alert_id.strip()
    if raw.startswith("alert-"):
        raw = raw[6:]
    try:
        return int(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid alert id") from e


_UI_STATUS = {
    "new": "NEW",
    "acknowledged": "ACKNOWLEDGED",
    "investigating": "INVESTIGATING",
    "assigned": "ASSIGNED",
    "resolved": "RESOLVED",
}


def update_alert(
    session: Session,
    alert_id: str,
    *,
    status: str | None = None,
    assigned_to_operator_id: int | None = None,
    actor_label: str | None = None,
    resolution: str | None = None,
) -> Alert:
    pk = _parse_alert_pk(alert_id)
    alert = session.get(Alert, pk)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    now = datetime.now(timezone.utc)
    meta = dict(alert.metadata_ or {})

    if status is not None:
        key = status.lower()
        db_status = _UI_STATUS.get(key, status.upper())
        try:
            new_status = AlertStatus(db_status)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from e
        current = alert.status
        if new_status != current and new_status not in _ALLOWED.get(current, set()):
            raise HTTPException(
                status_code=409,
                detail=f"Illegal transition {current.value} → {new_status.value}",
            )
        alert.status = new_status
        if new_status == AlertStatus.ACKNOWLEDGED and alert.acknowledged_at is None:
            alert.acknowledged_at = now
        if new_status == AlertStatus.RESOLVED:
            alert.resolved_at = now
            if resolution:
                meta["resolution"] = resolution

    if assigned_to_operator_id is not None:
        op = session.get(Operator, assigned_to_operator_id)
        if not op:
            raise HTTPException(status_code=404, detail="Operator not found")
        alert.assigned_to = assigned_to_operator_id
        alert.status = AlertStatus.ASSIGNED
        meta["assigned_to_label"] = op.full_name

    if actor_label:
        meta["last_actor_label"] = actor_label
        if assigned_to_operator_id is None and alert.status == AlertStatus.ASSIGNED:
            meta["assigned_to_label"] = actor_label

    alert.metadata_ = meta
    session.commit()
    session.refresh(alert)
    return alert


def list_site_alerts(
    session: Session,
    site_id: int,
    limit: int = 50,
    *,
    active_only: bool = False,
) -> list[Alert]:
    """Alerts tied to equipment or zones of this site. Unscoped rows are excluded."""
    site_eq = select(Equipment.equipment_id).where(Equipment.site_id == site_id)
    site_zn = select(Zone.zone_id).where(Zone.site_id == site_id)
    query = select(Alert).where(or_(Alert.equipment_id.in_(site_eq), Alert.zone_id.in_(site_zn)))
    if active_only:
        query = query.where(Alert.status != AlertStatus.RESOLVED)
    return list(
        session.scalars(
            query.order_by(Alert.created_at.desc()).limit(limit)
        ).all()
    )
