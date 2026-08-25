"""Apply pending simulation commands to SimulationWorld with full DB persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.enums import AlertSeverity
from app.db.models import MaintenanceEvent
from simulator.command_registry import (
    apply_runtime,
    canonical_action,
    equipment_kind,
    get_spec,
    restore_runtime,
)
from simulator.commands import SimulationCommand, load_all_commands, rewrite_commands
from simulator.generators.events import emit_fms_alert, emit_system_event, resolve_fms_alert
from simulator.state_machine import TruckPhase
from simulator.transition_service import transition_loader, transition_truck, truck_db_state
from simulator.world_model import ActiveInjection, SimulationWorld


@dataclass
class CommandContext:
    world: SimulationWorld
    session: Session
    sim_now: datetime
    open_states: dict[str, int]
    equip_id_by_code: dict[str, int]
    zone_id_by_code: dict[str, int]
    site_id: int


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fail(cmd: SimulationCommand, stage: str, reason: str) -> None:
    cmd.status = "FAILED"
    cmd.failure_stage = stage
    cmd.failure_reason = reason
    cmd.error = reason


def _format_alert(spec, target_id: str) -> tuple[str, str]:
    title = spec.title_template.format(target=target_id)
    desc = spec.description_template.format(target=target_id)
    return title, desc


def _persist_equipment_effects(
    ctx: CommandContext,
    cmd: SimulationCommand,
    inj: ActiveInjection | None,
) -> None:
    """DB state transition + alert + event for equipment commands."""
    tid = cmd.target_id
    spec = get_spec(cmd.action)
    if not spec:
        return

    if cmd.target_type == "EQUIPMENT" and equipment_kind(tid) == "TRUCK":
        truck = ctx.world.trucks.get(tid)
        if not truck:
            return
        transition_truck(
            ctx.session,
            ctx.open_states,
            truck,
            ctx.sim_now,
            ctx.site_id,
            source="COMMAND",
            message=f"{tid} → {truck_db_state(truck).value} (injection {cmd.action})",
        )
        emit_system_event(
            ctx.session,
            ctx.sim_now,
            spec.event_type,
            truck.equipment_id,
            f"{cmd.action} on {tid}",
        )
        if spec.alert and inj:
            title, desc = _format_alert(spec.alert, tid)
            emit_fms_alert(
                ctx.session,
                ctx.sim_now,
                spec.alert.alert_type,
                title,
                desc,
                truck.equipment_id,
                ctx.zone_id_by_code.get(truck.origin_zone_code),
                spec.alert.severity,
            )
            inj.alert_type = spec.alert.alert_type

        if canonical_action(cmd.action) == "MECHANICAL_BREAKDOWN":
            ctx.session.add(
                MaintenanceEvent(
                    equipment_id=truck.equipment_id,
                    type="BREAKDOWN",
                    component="Injected fault",
                    description=f"{tid} mechanical breakdown (test injection)",
                    start_time=ctx.sim_now,
                    severity=AlertSeverity.CRITICAL,
                    status="OPEN",
                    planned=False,
                )
            )

    elif cmd.target_type == "EQUIPMENT":
        ldr = ctx.world.loaders.get(tid)
        if not ldr:
            return
        transition_loader(
            ctx.session,
            ctx.open_states,
            ldr,
            ctx.sim_now,
            source="COMMAND",
            message=f"{tid} → injection {cmd.action}",
        )
        emit_system_event(ctx.session, ctx.sim_now, spec.event_type, ldr.equipment_id, f"{cmd.action} on {tid}")
        if spec.alert and inj:
            title, desc = _format_alert(spec.alert, tid)
            emit_fms_alert(
                ctx.session,
                ctx.sim_now,
                spec.alert.alert_type,
                title,
                desc,
                ldr.equipment_id,
                ctx.zone_id_by_code.get(ldr.zone_code),
                spec.alert.severity,
            )
            inj.alert_type = spec.alert.alert_type

        if canonical_action(cmd.action) == "MECHANICAL_BREAKDOWN":
            ctx.session.add(
                MaintenanceEvent(
                    equipment_id=ldr.equipment_id,
                    type="BREAKDOWN",
                    component="Injected fault",
                    description=f"{tid} mechanical breakdown (test injection)",
                    start_time=ctx.sim_now,
                    severity=AlertSeverity.CRITICAL,
                    status="OPEN",
                    planned=False,
                )
            )

    elif cmd.target_type == "ZONE":
        zone_id = ctx.zone_id_by_code.get(tid)
        emit_system_event(ctx.session, ctx.sim_now, spec.event_type, None, f"{cmd.action} on zone {tid}")
        if spec.alert:
            title, desc = _format_alert(spec.alert, tid)
            emit_fms_alert(
                ctx.session,
                ctx.sim_now,
                spec.alert.alert_type,
                title,
                desc,
                None,
                zone_id,
                spec.alert.severity,
            )
            if inj:
                inj.alert_type = spec.alert.alert_type

    elif cmd.target_type == "ROAD":
        emit_system_event(ctx.session, ctx.sim_now, spec.event_type, None, f"{cmd.action} on road {tid}")
        if spec.alert:
            title, desc = _format_alert(spec.alert, tid)
            emit_fms_alert(
                ctx.session,
                ctx.sim_now,
                spec.alert.alert_type,
                title,
                desc,
                None,
                None,
                spec.alert.severity,
            )
            if inj:
                inj.alert_type = spec.alert.alert_type


def _apply_command(ctx: CommandContext, cmd: SimulationCommand) -> ActiveInjection | None:
    action = canonical_action(cmd.action)
    tid = cmd.target_id

    if action == "RESTORE":
        _restore_target(ctx, cmd.target_type, tid)
        ctx.world.log_test(ctx.sim_now, f"{tid} RESTORE requested", cmd.target_type, tid)
        return None

    cmd.status = "VALIDATED"
    original = apply_runtime(ctx.world, cmd.target_type, tid, action, dict(cmd.parameters))
    cmd.original_state = original

    expires = None
    if cmd.duration_sec is not None:
        expires = (ctx.sim_now + timedelta(seconds=cmd.duration_sec)).isoformat()

    inj = ActiveInjection(
        injection_id=str(uuid4()),
        command_id=cmd.command_id,
        target_type=cmd.target_type,
        target_id=tid,
        action=action,
        parameters=dict(cmd.parameters),
        started_at=ctx.sim_now.isoformat(),
        expires_at=expires,
        ground_truth=f"{action} on {tid} at {ctx.sim_now.isoformat()}",
        original_state=original,
    )

    try:
        _persist_equipment_effects(ctx, cmd, inj)
        cmd.status = "PERSISTED"
    except Exception as exc:  # noqa: BLE001
        _fail(cmd, "DATABASE_PERSISTENCE", str(exc))
        raise

    ctx.world.add_injection(inj)
    dur = f" for {cmd.duration_sec}s" if cmd.duration_sec else " (until restore)"
    ctx.world.log_test(ctx.sim_now, f"{action} injected on {tid}{dur}", cmd.target_type, tid)
    ctx.world.log_sim(ctx.sim_now, f"{action} applied on {tid}", cmd.target_type, tid)
    return inj


def _restore_injection(ctx: CommandContext, inj: ActiveInjection, reason: str) -> None:
    tid = inj.target_id
    restore_runtime(ctx.world, inj.target_type, tid, inj.original_state or {})

    spec = get_spec(inj.action)
    if inj.target_type == "EQUIPMENT" and equipment_kind(tid) == "TRUCK":
        truck = ctx.world.trucks.get(tid)
        if truck:
            transition_truck(
                ctx.session,
                ctx.open_states,
                truck,
                ctx.sim_now,
                ctx.site_id,
                source="RECOVERY",
                message=f"{tid} restored ({reason})",
            )
            emit_system_event(
                ctx.session,
                ctx.sim_now,
                f"{inj.action}_RESTORED",
                truck.equipment_id,
                f"{tid} back to normal ({reason})",
            )
            if inj.alert_type:
                resolve_fms_alert(ctx.session, ctx.sim_now, inj.alert_type, equipment_id=truck.equipment_id)
    elif inj.target_type == "EQUIPMENT":
        ldr = ctx.world.loaders.get(tid)
        if ldr:
            transition_loader(
                ctx.session,
                ctx.open_states,
                ldr,
                ctx.sim_now,
                source="RECOVERY",
                message=f"{tid} restored ({reason})",
            )
            emit_system_event(
                ctx.session,
                ctx.sim_now,
                f"{inj.action}_RESTORED",
                ldr.equipment_id,
                f"{tid} back to normal ({reason})",
            )
            if inj.alert_type:
                resolve_fms_alert(ctx.session, ctx.sim_now, inj.alert_type, equipment_id=ldr.equipment_id)
    elif inj.target_type == "ZONE":
        zone_id = ctx.zone_id_by_code.get(tid)
        emit_system_event(ctx.session, ctx.sim_now, "ZONE_RESTORED", None, f"Zone {tid} restored ({reason})")
        if inj.alert_type:
            resolve_fms_alert(ctx.session, ctx.sim_now, inj.alert_type, zone_id=zone_id)
    elif inj.target_type == "ROAD":
        emit_system_event(ctx.session, ctx.sim_now, "ROAD_RESTORED", None, f"Road {tid} restored ({reason})")
        if inj.alert_type:
            resolve_fms_alert(ctx.session, ctx.sim_now, inj.alert_type)

    if spec:
        emit_system_event(ctx.session, ctx.sim_now, "INJECTION_RECOVERED", None, f"{tid} {inj.action} recovered")

    ctx.world.log_test(ctx.sim_now, f"{tid} restored ({reason})", inj.target_type, tid)
    ctx.world.log_sim(ctx.sim_now, f"{tid} back to normal operation", inj.target_type, tid)


def _restore_target(ctx: CommandContext, target_type: str, target_id: str) -> None:
    to_remove = [i for i in ctx.world.injections.values() if i.target_id == target_id]
    for inj in to_remove:
        ctx.world.remove_injection(inj.injection_id)
        _restore_injection(ctx, inj, "manual restore")


def _restore_by_command(ctx: CommandContext, cmd: SimulationCommand) -> None:
    for inj in list(ctx.world.injections.values()):
        if inj.command_id == cmd.command_id:
            ctx.world.remove_injection(inj.injection_id)
            _restore_injection(ctx, inj, "command cancelled")


def drain_commands_for_target(
    cmds: list[SimulationCommand],
    target_type: str,
    target_id: str,
) -> list[SimulationCommand]:
    """Return PENDING commands for a specific target, in order."""
    out: list[SimulationCommand] = []
    for cmd in cmds:
        if cmd.status != "PENDING":
            continue
        if cmd.target_type == target_type and cmd.target_id == target_id:
            out.append(cmd)
    return out


def apply_commands_for_target(
    ctx: CommandContext,
    cmds: list[SimulationCommand],
) -> list[SimulationCommand]:
    """Apply a batch of commands for one target. Marks statuses on cmd objects."""
    applied: list[SimulationCommand] = []
    for cmd in cmds:
        ready_at = _parse_dt(cmd.simulation_time)
        if ready_at and ctx.sim_now < ready_at:
            continue
        try:
            _apply_command(ctx, cmd)
            cmd.status = "APPLIED" if cmd.status == "PERSISTED" else cmd.status
            cmd.applied_at = ctx.sim_now.isoformat()
            if cmd.duration_sec is not None and not cmd.expires_at:
                cmd.expires_at = (ctx.sim_now + timedelta(seconds=cmd.duration_sec)).isoformat()
            applied.append(cmd)
        except Exception as exc:  # noqa: BLE001
            if cmd.status != "FAILED":
                _fail(cmd, "RUNTIME_APPLY", str(exc))
    return applied


def process_pending_commands(ctx: CommandContext) -> list[SimulationCommand]:
    """Apply all due PENDING commands (non per-target). Used when paused or for zone/road."""
    cmds = load_all_commands()
    applied: list[SimulationCommand] = []
    changed = False

    for cmd in cmds:
        if cmd.status == "CANCELLED" and cmd.command_id in {i.command_id for i in ctx.world.injections.values()}:
            _restore_by_command(ctx, cmd)
            changed = True
            continue

    # Zone, road, and loader equipment commands (not tied to truck loop)
    for cmd in cmds:
        if cmd.status != "PENDING":
            continue
        if cmd.target_type == "EQUIPMENT" and equipment_kind(cmd.target_id) == "TRUCK":
            continue  # handled per-truck in tick loop
        if cmd.target_type not in ("ZONE", "ROAD", "EQUIPMENT"):
            continue
        ready_at = _parse_dt(cmd.simulation_time)
        if ready_at and ctx.sim_now < ready_at:
            continue
        try:
            _apply_command(ctx, cmd)
            cmd.status = "APPLIED"
            cmd.applied_at = ctx.sim_now.isoformat()
            if cmd.duration_sec is not None:
                cmd.expires_at = (ctx.sim_now + timedelta(seconds=cmd.duration_sec)).isoformat()
            applied.append(cmd)
            changed = True
        except Exception as exc:  # noqa: BLE001
            _fail(cmd, "RUNTIME_APPLY", str(exc))
            changed = True

    # Auto-expire injections
    for inj in ctx.world.expire_due_injections(ctx.sim_now):
        _restore_injection(ctx, inj, "duration elapsed")
        for cmd in cmds:
            if cmd.command_id == inj.command_id and cmd.status in ("APPLIED", "PERSISTED"):
                cmd.status = "EXPIRED"
                changed = True

    if changed or applied:
        rewrite_commands(cmds)
    return applied


def process_equipment_commands(
    ctx: CommandContext,
    target_id: str,
    cmds: list[SimulationCommand],
) -> list[SimulationCommand]:
    """Apply pending equipment commands for one target during tick loop."""
    pending = drain_commands_for_target(cmds, "EQUIPMENT", target_id)
    if not pending:
        return []
    applied = apply_commands_for_target(ctx, pending)
    rewrite_commands(cmds)
    return applied
