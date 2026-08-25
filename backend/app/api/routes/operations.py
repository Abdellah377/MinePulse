from fastapi import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import Ctx, DbSession
from app.db.models import Cycle, Equipment, EquipmentState as EquipmentStateRow

router = APIRouter()


@router.get("/states")
def list_states(session: DbSession, ctx: Ctx):
    rows = session.scalars(
        select(EquipmentStateRow)
        .join(Equipment, Equipment.equipment_id == EquipmentStateRow.equipment_id)
        .where(
            Equipment.site_id == ctx.site_id,
            EquipmentStateRow.start_time < ctx.sim_now,
            or_(
                EquipmentStateRow.end_time.is_(None),
                EquipmentStateRow.end_time > ctx.shift_window_start,
            ),
        )
        .order_by(EquipmentStateRow.start_time.desc())
        .limit(200)
    ).all()
    return [
        {
            "id": r.state_id,
            "equipmentId": r.equipment_id,
            "state": r.state.value,
            "startTime": r.start_time.isoformat(),
            "endTime": r.end_time.isoformat() if r.end_time else None,
            "durationSec": r.duration_sec,
        }
        for r in rows
    ]


@router.get("/cycles")
def list_cycles(session: DbSession, ctx: Ctx):
    q = select(Cycle).join(Equipment, Equipment.equipment_id == Cycle.truck_id).where(
        Equipment.site_id == ctx.site_id
    )
    if ctx.shift_id is not None:
        q = q.where(
            or_(
                Cycle.shift_id == ctx.shift_id,
                (
                    Cycle.shift_id.is_(None)
                    & (Cycle.completed_at >= ctx.shift_window_start)
                    & (Cycle.completed_at < ctx.shift_window_end)
                ),
            )
        )
    else:
        q = q.where(
            Cycle.completed_at.is_not(None),
            Cycle.completed_at >= ctx.shift_window_start,
            Cycle.completed_at < ctx.shift_window_end,
        )
    rows = session.scalars(q.order_by(Cycle.started_at.desc()).limit(100)).all()
    return [
        {
            "id": r.cycle_id,
            "truckId": r.truck_id,
            "startedAt": r.started_at.isoformat(),
            "completedAt": r.completed_at.isoformat() if r.completed_at else None,
            "status": r.status,
            "totalDurationSec": r.total_duration_sec,
        }
        for r in rows
    ]
