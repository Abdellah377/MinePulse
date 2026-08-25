"""Authoritative current equipment assignment."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import EquipmentAssignment, Operator
from app.services.operational.context import OperationalContext

_ACTIVE_STATUSES = {"ACTIVE", "ASSIGNED", "IN_PROGRESS", "STARTED"}
ACTIVE_STATUSES = _ACTIVE_STATUSES


def current_assignment(
    session: Session,
    equipment_id: int,
    ctx: OperationalContext,
) -> EquipmentAssignment | None:
    """Most recent assignment that is still active for the current shift window."""
    q = (
        select(EquipmentAssignment)
        .where(
            EquipmentAssignment.truck_id == equipment_id,
            EquipmentAssignment.completed_at.is_(None),
            EquipmentAssignment.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(EquipmentAssignment.assigned_at.desc())
    )
    if ctx.shift_id is not None:
        q = q.where(
            or_(
                EquipmentAssignment.shift_id == ctx.shift_id,
                EquipmentAssignment.shift_id.is_(None),
            )
        )
    return session.scalar(q.limit(1))


def bulk_current_assignments(
    session: Session,
    equipment_ids: list[int],
    ctx: OperationalContext,
) -> dict[int, EquipmentAssignment]:
    if not equipment_ids:
        return {}
    q = (
        select(EquipmentAssignment)
        .where(
            EquipmentAssignment.truck_id.in_(equipment_ids),
            EquipmentAssignment.completed_at.is_(None),
            EquipmentAssignment.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(EquipmentAssignment.truck_id, EquipmentAssignment.assigned_at.desc())
    )
    if ctx.shift_id is not None:
        q = q.where(
            or_(
                EquipmentAssignment.shift_id == ctx.shift_id,
                EquipmentAssignment.shift_id.is_(None),
            )
        )
    rows = session.scalars(q).all()
    out: dict[int, EquipmentAssignment] = {}
    for row in rows:
        if row.truck_id is not None and row.truck_id not in out:
            out[row.truck_id] = row
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
