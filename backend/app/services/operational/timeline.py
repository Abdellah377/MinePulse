"""Shift-scoped Film timeline from equipment_states."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Equipment, EquipmentState as EquipmentStateRow
from app.mappers.enums import EQUIPMENT_STATE_TO_UI
from app.services.operational.context import OperationalContext


def timeline_for_shift(
    session: Session,
    ctx: OperationalContext,
    equip_codes: dict[int, str],
    zone_names: dict[int, str],
) -> list[dict]:
    """Return state segments overlapping the active shift window."""
    since = ctx.shift_window_start
    until = min(ctx.sim_now, ctx.shift_window_end)
    if until <= since:
        return []
    rows = session.scalars(
        select(EquipmentStateRow)
        .join(Equipment, Equipment.equipment_id == EquipmentStateRow.equipment_id)
        .where(
            Equipment.site_id == ctx.site_id,
            EquipmentStateRow.start_time < until,
            or_(EquipmentStateRow.end_time.is_(None), EquipmentStateRow.end_time > since),
        )
        .order_by(EquipmentStateRow.equipment_id, EquipmentStateRow.start_time)
    ).all()

    segments: list[dict] = []
    for r in rows:
        code = equip_codes.get(r.equipment_id)
        if not code:
            continue
        seg_start = max(r.start_time, since)
        seg_end = min(r.end_time or until, until)
        if seg_end <= seg_start:
            continue
        segments.append(
            {
                "id": f"seg-{r.state_id}",
                "equipmentId": code,
                "state": EQUIPMENT_STATE_TO_UI.get(r.state, "indetermine"),
                "start": int(seg_start.timestamp() * 1000),
                "end": int(seg_end.timestamp() * 1000),
                "zoneName": zone_names.get(r.zone_id) if r.zone_id else None,
            }
        )
    return segments
