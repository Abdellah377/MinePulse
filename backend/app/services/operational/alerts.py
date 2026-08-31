"""Alert mutations with validated state transitions."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.enums import AlertStatus
from app.db.models import Alert, Equipment, Operator, Zone

ALERT_PAGE_DEFAULT = 20
ALERT_PAGE_MAX = 50

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


def alert_operational_time(alert: Alert) -> datetime:
    """Return an alert's event time, with a legacy persistence-time fallback."""
    return alert.occurred_at or alert.created_at


def alert_operational_time_expression():
    """SQL expression matching :func:`alert_operational_time`."""
    return func.coalesce(Alert.occurred_at, Alert.created_at)


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


def encode_alert_cursor(when: datetime, alert_id: int) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    payload = json.dumps(
        {"t": when.astimezone(timezone.utc).isoformat(), "id": int(alert_id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_alert_cursor(cursor: str) -> tuple[datetime, int]:
    raw = cursor.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Invalid alert cursor")
    pad = "=" * ((4 - len(raw) % 4) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + pad))
        when = datetime.fromisoformat(str(data["t"]))
        alert_id = int(data["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid alert cursor") from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when, alert_id


def _site_scope(site_id: int):
    site_eq = select(Equipment.equipment_id).where(Equipment.site_id == site_id)
    site_zn = select(Zone.zone_id).where(Zone.site_id == site_id)
    return or_(
        Alert.site_id == site_id,
        Alert.equipment_id.in_(site_eq),
        Alert.zone_id.in_(site_zn),
    )


def count_active_alerts(session: Session, site_id: int) -> int:
    """Site-scoped unresolved count. Badge source of truth."""
    value = session.scalar(
        select(func.count())
        .select_from(Alert)
        .where(_site_scope(site_id), Alert.status != AlertStatus.RESOLVED)
    )
    return int(value or 0)


def paginate_alert_rows(
    rows: list[Alert],
    *,
    limit: int = ALERT_PAGE_DEFAULT,
    cursor: str | None = None,
    active_only: bool = False,
) -> dict[str, Any]:
    """In-memory cursor page used by tests; SQL path mirrors this ordering."""
    limit = max(1, min(int(limit), ALERT_PAGE_MAX))
    items = list(rows)
    if active_only:
        items = [row for row in items if row.status != AlertStatus.RESOLVED]
    items.sort(key=lambda row: (alert_operational_time(row), row.alert_id), reverse=True)
    if cursor:
        cursor_t, cursor_id = decode_alert_cursor(cursor)
        items = [
            row
            for row in items
            if (alert_operational_time(row), row.alert_id) < (cursor_t, cursor_id)
        ]
    has_more = len(items) > limit
    page = items[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_alert_cursor(alert_operational_time(last), last.alert_id)
    return {"items": page, "nextCursor": next_cursor, "hasMore": has_more}


def list_site_alerts(
    session: Session,
    site_id: int,
    limit: int = 50,
    *,
    active_only: bool = False,
) -> list[Alert]:
    """Site-scoped alerts, including equipment/zone-linked legacy rows."""
    query = select(Alert).where(_site_scope(site_id))
    if active_only:
        query = query.where(Alert.status != AlertStatus.RESOLVED)
    return list(
        session.scalars(
            query.order_by(
                alert_operational_time_expression().desc(),
                Alert.alert_id.desc(),
            ).limit(limit)
        ).all()
    )


def page_site_alerts(
    session: Session,
    site_id: int,
    *,
    limit: int = ALERT_PAGE_DEFAULT,
    cursor: str | None = None,
    active_only: bool = False,
) -> dict[str, Any]:
    """Newest-first cursor page. New arrivals do not appear inside older pages."""
    limit = max(1, min(int(limit), ALERT_PAGE_MAX))
    time_expr = alert_operational_time_expression()
    filters = [_site_scope(site_id)]
    if active_only:
        filters.append(Alert.status != AlertStatus.RESOLVED)
    if cursor:
        cursor_t, cursor_id = decode_alert_cursor(cursor)
        filters.append(
            or_(
                time_expr < cursor_t,
                and_(time_expr == cursor_t, Alert.alert_id < cursor_id),
            )
        )
    rows = list(
        session.scalars(
            select(Alert)
            .where(*filters)
            .order_by(time_expr.desc(), Alert.alert_id.desc())
            .limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_alert_cursor(alert_operational_time(last), last.alert_id)
    return {
        "items": page,
        "nextCursor": next_cursor,
        "hasMore": has_more,
        "activeCount": count_active_alerts(session, site_id),
    }
