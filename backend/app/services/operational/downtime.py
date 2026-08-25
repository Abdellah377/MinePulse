"""Shift-scoped downtime rollup — same function the API and future AI tools call."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState
from app.db.models import DowntimeEvent, Equipment, EquipmentState as EquipmentStateRow
from app.services.operational.context import OperationalContext
from app.services.operational.equipment import clip_interval_minutes

_STOP_STATES = (
    EquipmentState.STOPPED_MECHANICAL,
    EquipmentState.STOPPED_OPERATIONAL,
    EquipmentState.STOPPED_EXTERNAL,
    EquipmentState.STOPPED_UNDEFINED,
    EquipmentState.MAINTENANCE,
    EquipmentState.NO_DATA,
)

_STATE_LABEL = {
    EquipmentState.STOPPED_MECHANICAL: "Arrêt matériel",
    EquipmentState.STOPPED_OPERATIONAL: "Arrêt exploitation",
    EquipmentState.STOPPED_EXTERNAL: "Arrêt extérieur",
    EquipmentState.STOPPED_UNDEFINED: "Arrêt non défini",
    EquipmentState.MAINTENANCE: "Maintenance",
    EquipmentState.NO_DATA: "Perte communication",
}


def downtime_reasons(session: Session, ctx: OperationalContext) -> list[dict]:
    """Hours by reason clipped to the active shift window. Never invents status."""
    site_id = ctx.site_id
    since, until = ctx.shift_window_start, ctx.sim_now
    events = session.scalars(
        select(DowntimeEvent)
        .join(Equipment, Equipment.equipment_id == DowntimeEvent.equipment_id)
        .where(
            Equipment.site_id == site_id,
            DowntimeEvent.start_time < until,
            or_(DowntimeEvent.end_time.is_(None), DowntimeEvent.end_time > since),
        )
    ).all()
    by_reason: dict[str, float] = defaultdict(float)
    for e in events:
        hours = clip_interval_minutes(e.start_time, e.end_time, since, until) / 60.0
        if hours > 0:
            by_reason[e.category or "Autre"] += hours

    if not by_reason:
        rows = session.scalars(
            select(EquipmentStateRow)
            .join(Equipment, Equipment.equipment_id == EquipmentStateRow.equipment_id)
            .where(
                Equipment.site_id == site_id,
                EquipmentStateRow.state.in_(_STOP_STATES),
                EquipmentStateRow.start_time < until,
                or_(EquipmentStateRow.end_time.is_(None), EquipmentStateRow.end_time > since),
            )
        ).all()
        for r in rows:
            hours = clip_interval_minutes(r.start_time, r.end_time, since, until) / 60.0
            if hours <= 0:
                continue
            by_reason[_STATE_LABEL.get(r.state, "Autre")] += hours

    return [{"reason": k, "hours": round(v, 2)} for k, v in sorted(by_reason.items(), key=lambda x: -x[1])]
