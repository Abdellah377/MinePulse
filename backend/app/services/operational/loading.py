"""Authoritative bounded loading-point and queue context."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.enums import EquipmentState, EquipmentType
from app.db.models import Cycle, CycleStage, Equipment, EquipmentState as EquipmentStateRow
from app.services.operational.assignments import bulk_current_assignments
from app.services.operational.context import OperationalContext

MAX_LOADERS = 6
MAX_WAITING_TRUCKS_PER_LOADER = 8
MAX_LOADING_STAGE_SAMPLES = 8
_LOADER_TYPES = {EquipmentType.EXCAVATOR, EquipmentType.LOADER}


def resolve_relevant_loader_ids(
    *,
    loader_ids: list[int] | None,
    equipment_by_id: dict[int, Equipment],
    assignments: dict,
    equipment_id: int | None,
    zone_id: int | None,
) -> list[int]:
    """Choose which loaders get an authoritative queue row.

    Explicit optimizer ``loader_ids`` skip assignment-based discovery.
    Unknown, inactive, or non-loader IDs are omitted — never invented as zero.
    """
    if loader_ids is not None:
        relevant: list[int] = []
        for loader_id in loader_ids:
            row = equipment_by_id.get(loader_id)
            if row is None or not row.active or row.type not in _LOADER_TYPES:
                continue
            if loader_id not in relevant:
                relevant.append(loader_id)
            if len(relevant) >= MAX_LOADERS:
                break
        return relevant

    relevant_loader_ids: list[int] = []
    target = equipment_by_id.get(equipment_id) if equipment_id is not None else None
    target_assignment = assignments.get(equipment_id) if equipment_id is not None else None
    if target and target.type in _LOADER_TYPES:
        relevant_loader_ids.append(target.equipment_id)
    if target_assignment and target_assignment.loader_id is not None:
        relevant_loader_ids.append(target_assignment.loader_id)
    for assignment in assignments.values():
        if assignment.loader_id is None:
            continue
        if zone_id is not None and assignment.origin_zone_id != zone_id:
            continue
        relevant_loader_ids.append(assignment.loader_id)
    if not relevant_loader_ids:
        for assignment in assignments.values():
            if assignment.loader_id is not None:
                relevant_loader_ids.append(assignment.loader_id)
    return list(dict.fromkeys(relevant_loader_ids))[:MAX_LOADERS]


def _minutes(start: datetime, end: datetime) -> float:
    def utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    return round(max(0.0, (utc(end) - utc(start)).total_seconds() / 60.0), 1)


def summarize_loading_durations(samples: list[dict]) -> dict:
    """Compare recent completed loading stages with an earlier bounded baseline."""
    completed = [row for row in samples if row.get("endTime") and row.get("durationMinutes") is not None]
    completed.sort(key=lambda row: row["endTime"])
    recent = completed[-3:]
    baseline = completed[-11:-3]
    recent_avg = round(mean(row["durationMinutes"] for row in recent), 1) if recent else None
    baseline_avg = round(mean(row["durationMinutes"] for row in baseline), 1) if baseline else None
    change = None
    if recent_avg is not None and baseline_avg is not None and baseline_avg > 0:
        change = round(((recent_avg - baseline_avg) / baseline_avg) * 100.0, 1)
    return {
        "recentAverageLoadingMinutes": recent_avg,
        "recentSampleCount": len(recent),
        "baselineAverageLoadingMinutes": baseline_avg,
        "baselineSampleCount": len(baseline),
        "loadingDurationChangePct": change,
    }


def loading_service_context(
    session: Session,
    ctx: OperationalContext,
    *,
    equipment_id: int | None = None,
    zone_id: int | None = None,
    loader_ids: list[int] | None = None,
) -> dict:
    """Relate waiting trucks to shared loaders and observed loading-stage durations.

    This is an operational definition over persisted assignments, equipment
    states, cycles, and cycle stages.  It contains no simulator metadata or AI
    inference.
    """
    equipment = list(
        session.scalars(
            select(Equipment)
            .where(Equipment.site_id == ctx.site_id, Equipment.active.is_(True))
            .order_by(Equipment.equipment_id)
        ).all()
    )
    by_id = {row.equipment_id: row for row in equipment}
    truck_ids = [row.equipment_id for row in equipment if row.type == EquipmentType.HAUL_TRUCK]
    assignments = bulk_current_assignments(session, truck_ids, ctx)

    relevant_loader_ids = resolve_relevant_loader_ids(
        loader_ids=loader_ids,
        equipment_by_id=by_id,
        assignments=assignments,
        equipment_id=equipment_id,
        zone_id=zone_id,
    )

    current_state_rows = list(
        session.scalars(
            select(EquipmentStateRow)
            .where(
                EquipmentStateRow.equipment_id.in_(truck_ids),
                EquipmentStateRow.start_time <= ctx.sim_now,
                or_(
                    EquipmentStateRow.end_time.is_(None),
                    EquipmentStateRow.end_time > ctx.sim_now,
                ),
            )
            .order_by(EquipmentStateRow.equipment_id, EquipmentStateRow.start_time.desc())
        ).all()
    ) if truck_ids else []
    current_state_by_truck: dict[int, EquipmentStateRow] = {}
    for row in current_state_rows:
        current_state_by_truck.setdefault(row.equipment_id, row)

    cycle_filter = [
        Equipment.site_id == ctx.site_id,
        CycleStage.stage == EquipmentState.LOADING,
        CycleStage.start_time >= ctx.shift_window_start,
        CycleStage.start_time <= ctx.sim_now,
    ]
    if relevant_loader_ids:
        cycle_filter.append(Cycle.loader_id.in_(relevant_loader_ids))
    if zone_id is not None:
        cycle_filter.append(CycleStage.zone_id == zone_id)
    if ctx.shift_id is not None:
        cycle_filter.append(or_(Cycle.shift_id == ctx.shift_id, Cycle.shift_id.is_(None)))
    stage_rows = list(
        session.execute(
            select(Cycle, CycleStage)
            .join(Equipment, Equipment.equipment_id == Cycle.truck_id)
            .join(CycleStage, CycleStage.cycle_id == Cycle.cycle_id)
            .where(and_(*cycle_filter))
            .order_by(CycleStage.start_time.desc())
            .limit(MAX_LOADERS * MAX_LOADING_STAGE_SAMPLES)
        ).all()
    )

    stages_by_loader: dict[int, list[dict]] = {}
    record_ids: list[str] = []
    for cycle, stage in stage_rows:
        if cycle.loader_id is None:
            continue
        end = stage.end_time if stage.end_time is not None else ctx.sim_now
        duration = (
            round(float(stage.duration_sec) / 60.0, 1)
            if stage.duration_sec is not None
            else _minutes(stage.start_time, end)
        )
        stages_by_loader.setdefault(cycle.loader_id, []).append(
            {
                "cycleStageId": stage.cycle_stage_id,
                "cycleId": cycle.cycle_id,
                "truckId": cycle.truck_id,
                "zoneId": stage.zone_id,
                "startTime": stage.start_time,
                "endTime": stage.end_time,
                "durationMinutes": duration,
                "completed": stage.end_time is not None,
            }
        )
        record_ids.extend([f"cycle:{cycle.cycle_id}", f"cycle-stage:{stage.cycle_stage_id}"])

    loader_rows = []
    for loader_id in relevant_loader_ids:
        loader = by_id.get(loader_id)
        if loader is None:
            continue
        loader_assignments = [
            row for row in assignments.values()
            if row.loader_id == loader_id and (zone_id is None or row.origin_zone_id == zone_id)
        ]
        record_ids.extend(f"assignment:{row.assignment_id}" for row in loader_assignments)
        waiting = []
        for assignment in loader_assignments:
            if assignment.truck_id is None:
                continue
            state = current_state_by_truck.get(assignment.truck_id)
            if state is None or state.state != EquipmentState.WAITING_LOADING:
                continue
            truck = by_id.get(assignment.truck_id)
            waiting.append(
                {
                    "truckId": assignment.truck_id,
                    "truckCode": truck.code if truck else None,
                    "zoneId": state.zone_id or assignment.origin_zone_id,
                    "waitingStartedAt": state.start_time,
                    "waitingMinutes": _minutes(state.start_time, ctx.sim_now),
                    "assignmentId": assignment.assignment_id,
                }
            )
            record_ids.extend([f"assignment:{assignment.assignment_id}", f"state:{state.state_id}"])
        waiting.sort(key=lambda row: row["waitingMinutes"], reverse=True)
        samples = sorted(
            stages_by_loader.get(loader_id, []),
            key=lambda row: row["startTime"],
        )[-MAX_LOADING_STAGE_SAMPLES:]
        loader_rows.append(
            {
                "loaderId": loader_id,
                "loaderCode": loader.code,
                "loaderType": loader.type.value,
                "loaderState": loader.current_state.value,
                "activeAssignmentCount": len(loader_assignments),
                "waitingTruckCount": len(waiting),
                "waitingTrucks": waiting[:MAX_WAITING_TRUCKS_PER_LOADER],
                **summarize_loading_durations(samples),
                "representativeLoadingStages": samples,
            }
        )

    return {
        "siteId": ctx.site_id,
        "shiftId": ctx.shift_id,
        "windowStart": ctx.shift_window_start,
        "windowEnd": ctx.sim_now,
        "targetEquipmentId": equipment_id,
        "targetZoneId": zone_id,
        "loaders": loader_rows,
        "bounds": {
            "maxLoaders": MAX_LOADERS,
            "maxWaitingTrucksPerLoader": MAX_WAITING_TRUCKS_PER_LOADER,
            "maxLoadingStageSamplesPerLoader": MAX_LOADING_STAGE_SAMPLES,
        },
        "sourceRecordIds": list(dict.fromkeys(record_ids)),
    }
