"""Simulation control + inject API.

The tick loop runs embedded inside the FastAPI process (see simulator.service).
Start / Pause / Reset / Inject are fully controlled from Simulation Centre —
no separate `python -m simulator run` terminal is required.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.enums import AlertSource, AlertStatus
from app.db.models import Alert, Equipment, EquipmentState as EquipmentStateRow, HaulRoad, Site, SystemEvent, Zone
from app.schemas.simulation import CausalScenarioStartBody, InjectBody, ModeBody, ScenarioBody, SpeedBody
from fastapi import Depends
from simulator.commands import (
    SimulationCommand,
    append_command,
    cancel_command,
    load_all_commands,
    read_event_log,
)
from simulator.causal_scenarios import scenario_catalog
from simulator.control import (
    VALID_SPEEDS,
    patch_control_mode,
    patch_control_speed,
    read_control,
    read_heartbeat,
)
from simulator.service import get_simulation_service
from simulator.world_model import SimulationWorld

router = APIRouter()

CONTROL_NOTE = (
    "Simulateur intégré à l'API — Start / Pause / Reset depuis le Centre de simulation."
)


def _with_note(data: dict) -> dict:
    svc = get_simulation_service()
    return {
        **data,
        "note": CONTROL_NOTE,
        **svc.status_extra(),
    }


def _heartbeat_status() -> dict:
    svc = get_simulation_service()
    hb = read_heartbeat()
    if not hb or not hb.get("recorded_at"):
        return {
            "engine_alive": svc.running and svc.last_error is None,
            "last_heartbeat_age_sec": None,
        }
    try:
        ts = datetime.fromisoformat(hb["recorded_at"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        # Alive if recent heartbeat OR tick thread is up (paused still heartbeats)
        alive = (age < 10.0) or (svc.running and svc.last_error is None)
        return {"engine_alive": alive, "last_heartbeat_age_sec": round(age, 2)}
    except (TypeError, ValueError):
        return {"engine_alive": svc.running, "last_heartbeat_age_sec": None}


@router.get("/status")
def simulation_status():
    control = read_control()
    snap = SimulationWorld.read_runtime_snapshot()
    return _with_note(
        {
            **control,
            **_heartbeat_status(),
            "runtime": {
                "injections": snap.get("injections", []),
                "causal_scenarios": snap.get("causal_scenarios", []),
                "zone_queues": {
                    k: {"queue": v.get("queue", []), "occupants": v.get("occupants", []), "capacity": v.get("capacity")}
                    for k, v in (snap.get("zones") or {}).items()
                },
                "truck_count": len(snap.get("trucks") or {}),
            },
        }
    )


@router.post("/start")
def start_simulation():
    svc = get_simulation_service()
    try:
        return _with_note(svc.start_simulation())
    except Exception as e:
        raise HTTPException(500, f"Impossible de démarrer le simulateur: {e}") from e


@router.post("/pause")
def pause_simulation():
    return _with_note(get_simulation_service().pause_simulation())


@router.post("/resume")
def resume_simulation():
    return _with_note(get_simulation_service().resume_simulation())


@router.post("/reset")
def reset_simulation():
    try:
        return _with_note(get_simulation_service().reset_simulation())
    except Exception as e:
        raise HTTPException(500, f"Reset échoué: {e}") from e


@router.post("/speed")
def set_speed(body: SpeedBody):
    try:
        return _with_note(patch_control_speed(body.speed))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/mode")
def set_mode(body: ModeBody):
    try:
        return _with_note(patch_control_mode(body.mode))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/scenario")
def set_scenario(body: ScenarioBody):
    control = read_control()
    control["scenario"] = body.scenario
    from simulator.control import write_control

    write_control(control)
    return _with_note(control)


@router.get("/causal-scenarios")
def list_causal_scenarios():
    """Developer-only catalog/status; it is not an operational or AI API."""
    return {
        "catalog": scenario_catalog(include_hidden=True),
        "active": get_simulation_service().causal_scenario_status(),
    }


@router.post("/causal-scenarios/{scenario_id}/start")
def start_causal_scenario(scenario_id: str, body: CausalScenarioStartBody):
    try:
        run = get_simulation_service().activate_causal_scenario(
            scenario_id,
            body.target_id,
            duration_min=body.duration_min,
            seed=body.seed,
        )
        return {"ok": True, "run": run}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/causal-scenarios/{run_id}")
def stop_causal_scenario(run_id: str):
    try:
        run = get_simulation_service().stop_causal_scenario(run_id)
        return {"ok": True, "run": run}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/speeds")
def list_speeds():
    return {"speeds": list(VALID_SPEEDS)}


@router.get("/equipment")
def list_sim_equipment():
    snap = SimulationWorld.read_runtime_snapshot()
    trucks = snap.get("trucks") or {}
    loaders = snap.get("loaders") or {}
    rows = []
    for code, t in trucks.items():
        rows.append(
            {
                "code": code,
                "type": "HAUL_TRUCK",
                "state": t.get("phase"),
                "speed_kmh": t.get("speed_kmh"),
                "payload_t": t.get("payload_t"),
                "fuel_pct": t.get("fuel_pct"),
                "comm_lost": t.get("comm_lost"),
                "origin": t.get("origin"),
                "dest": t.get("dest"),
                "loader": t.get("loader"),
                "road": t.get("road"),
            }
        )
    for code, l in loaders.items():
        rows.append(
            {
                "code": code,
                "type": "EXCAVATOR" if code.startswith("EXC") else "LOADER",
                "state": "BREAKDOWN" if l.get("mechanical_breakdown") else "AVAILABLE",
                "capacity_factor": l.get("capacity_factor"),
                "zone": l.get("zone_code"),
            }
        )
    return rows


@router.get("/equipment/{code}")
def get_sim_equipment(code: str):
    snap = SimulationWorld.read_runtime_snapshot()
    if code in (snap.get("trucks") or {}):
        return {"code": code, "type": "HAUL_TRUCK", **snap["trucks"][code]}
    if code in (snap.get("loaders") or {}):
        return {"code": code, "type": "EXCAVATOR", **snap["loaders"][code]}
    raise HTTPException(404, f"Equipment {code} not in runtime snapshot (is simulator running?)")


@router.post("/inject")
def inject_command(body: InjectBody):
    cmd = SimulationCommand.create(
        target_type=body.target_type,
        target_id=body.target_id,
        action=body.action,
        parameters=body.parameters,
        duration_sec=body.duration_sec,
        simulation_time=body.simulation_time,
    )
    append_command(cmd)
    return {"ok": True, "command": cmd.__dict__, "note": CONTROL_NOTE}


@router.post("/equipment/{code}/inject")
def inject_equipment(code: str, body: InjectBody):
    return inject_command(
        InjectBody(
            target_type="EQUIPMENT",
            target_id=code,
            action=body.action,
            parameters=body.parameters,
            duration_sec=body.duration_sec,
            simulation_time=body.simulation_time,
        )
    )


@router.get("/zones")
def list_sim_zones(session: Session = Depends(get_db)):
    site = session.scalar(select(Site).where(Site.code == "MP-SIM-01"))
    if not site:
        return []
    zones = session.scalars(select(Zone).where(Zone.site_id == site.site_id)).all()
    snap = SimulationWorld.read_runtime_snapshot().get("zones") or {}
    out = []
    for z in zones:
        rt = snap.get(z.code, {})
        out.append(
            {
                "code": z.code,
                "name": z.name,
                "type": z.type.value if hasattr(z.type, "value") else str(z.type),
                "capacity": rt.get("capacity", z.capacity),
                "base_capacity": rt.get("base_capacity", z.capacity),
                "closed": rt.get("closed", False),
                "queue": rt.get("queue", []),
                "occupants": rt.get("occupants", []),
            }
        )
    return out


@router.post("/zones/{code}/inject")
def inject_zone(code: str, body: InjectBody):
    return inject_command(
        InjectBody(
            target_type="ZONE",
            target_id=code,
            action=body.action,
            parameters=body.parameters,
            duration_sec=body.duration_sec,
            simulation_time=body.simulation_time,
        )
    )


@router.get("/roads")
def list_sim_roads(session: Session = Depends(get_db)):
    site = session.scalar(select(Site).where(Site.code == "MP-SIM-01"))
    if not site:
        return []
    roads = session.scalars(select(HaulRoad).where(HaulRoad.site_id == site.site_id)).all()
    snap = SimulationWorld.read_runtime_snapshot().get("roads") or {}
    zone_codes = {z.zone_id: z.code for z in session.scalars(select(Zone).where(Zone.site_id == site.site_id)).all()}
    out = []
    for r in roads:
        rt = snap.get(r.code, {})
        out.append(
            {
                "code": r.code,
                "name": r.name,
                "from_zone": zone_codes.get(r.from_zone_id, ""),
                "to_zone": zone_codes.get(r.to_zone_id, ""),
                "distance_km": float(r.distance_km or 0),
                "speed_limit": rt.get("speed_limit", float(r.speed_limit_kmh or 40)),
                "closed": rt.get("closed", False),
            }
        )
    return out


@router.post("/roads/{code}/inject")
def inject_road(code: str, body: InjectBody):
    return inject_command(
        InjectBody(
            target_type="ROAD",
            target_id=code,
            action=body.action,
            parameters=body.parameters,
            duration_sec=body.duration_sec,
            simulation_time=body.simulation_time,
        )
    )


@router.get("/injections")
def list_injections():
    snap = SimulationWorld.read_runtime_snapshot()
    cmds = [c for c in load_all_commands() if c.status in ("PENDING", "APPLIED")]
    return {
        "active": snap.get("injections", []),
        "commands": [c.__dict__ for c in cmds[-50:]],
    }


@router.delete("/injections/{command_id}")
def delete_injection(command_id: str):
    """Cancel a command / request restore of its injection."""
    cmd = cancel_command(command_id)
    if not cmd:
        raise HTTPException(404, "Command not found")
    # Also queue an explicit RESTORE for applied injections
    if cmd.status == "CANCELLED" and cmd.target_id:
        restore = SimulationCommand.create(
            target_type=cmd.target_type,
            target_id=cmd.target_id,
            action="RESTORE",
        )
        append_command(restore)
    return {"ok": True, "command": cmd.__dict__}


@router.get("/log")
def simulation_log(limit: int = 100):
    return read_event_log(limit=limit)


@router.get("/propagation/{code}")
def propagation_status(code: str, session: Session = Depends(get_db)):
    """Runtime + DB + API state comparison for any target (equipment, zone, road)."""
    snap = SimulationWorld.read_runtime_snapshot()
    site = session.scalar(select(Site).where(Site.code == "MP-SIM-01"))
    if not site:
        raise HTTPException(404, "Site not found")

    cmds = load_all_commands()
    target_cmds = [c for c in cmds if c.target_id == code]
    latest_cmd = target_cmds[-1] if target_cmds else None

    result: dict = {
        "target": code,
        "command_status": latest_cmd.status if latest_cmd else None,
        "active_command_id": latest_cmd.command_id if latest_cmd else None,
        "failure_stage": latest_cmd.failure_stage if latest_cmd else None,
        "failure_reason": latest_cmd.failure_reason if latest_cmd else None,
        "checks": {},
    }

    hb = _heartbeat_status()
    result["checks"]["engine_online"] = hb["engine_alive"]

    if latest_cmd:
        result["checks"]["command_received"] = True
        result["checks"]["command_validated"] = latest_cmd.status in (
            "VALIDATED",
            "APPLIED",
            "PERSISTED",
            "EXPIRED",
        )
        result["checks"]["command_applied"] = latest_cmd.status in ("APPLIED", "PERSISTED", "EXPIRED")
        result["checks"]["command_persisted"] = latest_cmd.status in ("PERSISTED", "EXPIRED")
        result["checks"]["command_failed"] = latest_cmd.status == "FAILED"
    else:
        result["checks"]["command_received"] = False

    active_injections = [i for i in (snap.get("injections") or []) if i.get("target_id") == code]
    result["active_injections"] = active_injections
    result["checks"]["runtime_effect"] = len(active_injections) > 0 or (
        code in (snap.get("trucks") or {}) or code in (snap.get("loaders") or {})
    )

    # Equipment path
    eq = session.scalar(select(Equipment).where(Equipment.code == code, Equipment.site_id == site.site_id))
    if eq:
        runtime = (snap.get("trucks") or {}).get(code) or (snap.get("loaders") or {}).get(code)
        result["runtime"] = runtime
        result["db_current_state"] = eq.current_state.value if eq.current_state else None
        result["checks"]["api_observes_change"] = eq.current_state is not None

        open_state = session.scalar(
            select(EquipmentStateRow)
            .where(EquipmentStateRow.equipment_id == eq.equipment_id, EquipmentStateRow.end_time.is_(None))
            .order_by(EquipmentStateRow.start_time.desc())
        )
        if open_state:
            result["open_state_interval"] = {
                "state_id": open_state.state_id,
                "state": open_state.state.value,
                "start_time": open_state.start_time.isoformat(),
                "end_time": None,
            }
            result["checks"]["db_state_persisted"] = True
        else:
            result["checks"]["db_state_persisted"] = False

        open_alerts = session.scalars(
            select(Alert).where(
                Alert.equipment_id == eq.equipment_id,
                Alert.source == AlertSource.FMS,
                Alert.status.in_(
                    (AlertStatus.NEW, AlertStatus.ACKNOWLEDGED, AlertStatus.INVESTIGATING, AlertStatus.ASSIGNED)
                ),
            )
        ).all()
        result["open_alerts"] = [
            {"alert_id": a.alert_id, "alert_type": a.alert_type, "title": a.title, "status": a.status.value}
            for a in open_alerts
        ]
        result["checks"]["fms_alert_generated"] = len(open_alerts) > 0

        events = session.scalars(
            select(SystemEvent)
            .where(SystemEvent.equipment_id == eq.equipment_id)
            .order_by(SystemEvent.ts.desc())
            .limit(5)
        ).all()
        result["last_events"] = [
            {"event_type": e.event_type, "message": e.message, "ts": e.ts.isoformat()} for e in events
        ]
        result["checks"]["system_event_generated"] = len(events) > 0
        return result

    # Zone path
    zone = session.scalar(select(Zone).where(Zone.code == code, Zone.site_id == site.site_id))
    if zone:
        rt = (snap.get("zones") or {}).get(code, {})
        result["runtime"] = rt
        result["checks"]["db_state_persisted"] = rt.get("closed") is not None or rt.get("capacity") is not None
        open_alerts = session.scalars(
            select(Alert).where(
                Alert.zone_id == zone.zone_id,
                Alert.source == AlertSource.FMS,
                Alert.status.in_(
                    (AlertStatus.NEW, AlertStatus.ACKNOWLEDGED, AlertStatus.INVESTIGATING, AlertStatus.ASSIGNED)
                ),
            )
        ).all()
        result["open_alerts"] = [
            {"alert_id": a.alert_id, "alert_type": a.alert_type, "title": a.title} for a in open_alerts
        ]
        result["checks"]["fms_alert_generated"] = len(open_alerts) > 0
        events = session.scalars(
            select(SystemEvent).where(SystemEvent.message.contains(code)).order_by(SystemEvent.ts.desc()).limit(5)
        ).all()
        result["last_events"] = [{"event_type": e.event_type, "message": e.message} for e in events]
        result["checks"]["system_event_generated"] = len(events) > 0
        return result

    # Road path
    road = session.scalar(select(HaulRoad).where(HaulRoad.code == code, HaulRoad.site_id == site.site_id))
    if road:
        rt = (snap.get("roads") or {}).get(code, {})
        result["runtime"] = rt
        result["checks"]["db_road_status"] = not rt.get("closed", False) if rt else None
        result["checks"]["runtime_effect"] = bool(rt)
        events = session.scalars(
            select(SystemEvent).where(SystemEvent.message.contains(code)).order_by(SystemEvent.ts.desc()).limit(5)
        ).all()
        result["last_events"] = [{"event_type": e.event_type, "message": e.message} for e in events]
        result["checks"]["system_event_generated"] = len(events) > 0
        return result

    raise HTTPException(404, f"Target {code} not found")
