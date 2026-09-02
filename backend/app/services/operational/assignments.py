"""Authoritative current equipment assignment."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import EquipmentAssignment, Operator
from app.services.operational.context import OperationalContext

_ACTIVE_STATUSES = {"ACTIVE", "ASSIGNED", "IN_PROGRESS", "STARTED"}
_VISIBLE_STATUSES = _ACTIVE_STATUSES | {"COMPLETED"}
ACTIVE_STATUSES = _ACTIVE_STATUSES


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def assignment_covers_sim_now(row: EquipmentAssignment, sim_now: datetime | None) -> bool:
    """True when the row is the haul assignment in force at sim_now.

    Live ``COMPLETED`` rows still count if they were open at sim_now. A missing
    metric stays missing — this does not invent destinations.
    """
    now = _aware(sim_now)
    if now is None:
        return row.completed_at is None and row.status in _ACTIVE_STATUSES
    assigned = _aware(row.assigned_at)
    if assigned is not None and assigned > now:
        return False
    completed = _aware(row.completed_at)
    if completed is not None and completed <= now:
        return False
    return True


def select_current_assignment(
    rows: list[EquipmentAssignment],
    ctx: OperationalContext,
) -> EquipmentAssignment | None:
    """Prefer the current-shift covering row; otherwise any covering row."""
    covering = [
        row
        for row in rows
        if assignment_covers_sim_now(row, ctx.sim_now) and row.status in _VISIBLE_STATUSES
    ]
    if not covering:
        return None
    covering.sort(key=lambda row: _aware(row.assigned_at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    if ctx.shift_id is not None:
        preferred = [row for row in covering if row.shift_id == ctx.shift_id or row.shift_id is None]
        if preferred:
            return preferred[0]
    return covering[0]


def _covering_query(equipment_ids: list[int], ctx: OperationalContext):
    q = select(EquipmentAssignment).where(
        EquipmentAssignment.truck_id.in_(equipment_ids),
        EquipmentAssignment.status.in_(_VISIBLE_STATUSES),
        or_(
            EquipmentAssignment.completed_at.is_(None),
            EquipmentAssignment.completed_at > ctx.sim_now,
        ),
    )
    if ctx.sim_now is not None:
        q = q.where(EquipmentAssignment.assigned_at <= ctx.sim_now)
    return q.order_by(EquipmentAssignment.truck_id, EquipmentAssignment.assigned_at.desc())


def current_assignment(
    session: Session,
    equipment_id: int,
    ctx: OperationalContext,
) -> EquipmentAssignment | None:
    """Haul assignment in force for the truck at the operational clock."""
    rows = list(session.scalars(_covering_query([equipment_id], ctx)).all())
    return select_current_assignment(rows, ctx)


def bulk_current_assignments(
    session: Session,
    equipment_ids: list[int],
    ctx: OperationalContext,
) -> dict[int, EquipmentAssignment]:
    if not equipment_ids:
        return {}
    rows = list(session.scalars(_covering_query(equipment_ids, ctx)).all())
    grouped: dict[int, list[EquipmentAssignment]] = {}
    for row in rows:
        if row.truck_id is None:
            continue
        grouped.setdefault(row.truck_id, []).append(row)
    out: dict[int, EquipmentAssignment] = {}
    for truck_id, group in grouped.items():
        chosen = select_current_assignment(group, ctx)
        if chosen is not None:
            out[truck_id] = chosen
    return out


def operators_for_site_equipment(
    session: Session,
    equipment_ids: list[int],
    extra_operator_ids: list[int] | None = None,
    limit: int = 20,
) -> list[Operator]:
    """Operators assigned to site equipment (plus optional extra ids, e.g. alert assignees)."""
    op_ids: set[int] = set(extra_operator_ids or [])
    if equipment_ids:
        rows = session.scalars(
            select(EquipmentAssignment.operator_id).where(
                EquipmentAssignment.operator_id.is_not(None),
                or_(
                    EquipmentAssignment.truck_id.in_(equipment_ids),
                    EquipmentAssignment.loader_id.in_(equipment_ids),
                ),
            )
        ).all()
        op_ids.update(int(i) for i in rows if i is not None)
    if not op_ids:
        return []
    return list(
        session.scalars(select(Operator).where(Operator.operator_id.in_(op_ids)).limit(limit)).all()
    )
