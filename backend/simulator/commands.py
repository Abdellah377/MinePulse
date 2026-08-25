"""Simulation command queue — JSONL pending commands for the tick process."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simulator.control import COMMANDS_PATH, EVENT_LOG_PATH


@dataclass
class SimulationCommand:
    command_id: str
    created_at: str
    simulation_time: str | None  # apply at/after this sim time; null = ASAP
    target_type: str  # EQUIPMENT | ZONE | ROAD | SYSTEM
    target_id: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    duration_sec: int | None = None  # None = until manual restore
    status: str = "PENDING"  # PENDING | VALIDATED | APPLIED | PERSISTED | CANCELLED | EXPIRED | FAILED
    applied_at: str | None = None
    expires_at: str | None = None
    error: str | None = None
    failure_stage: str | None = None
    failure_reason: str | None = None
    original_state: dict[str, Any] | None = None

    @staticmethod
    def create(
        *,
        target_type: str,
        target_id: str,
        action: str,
        parameters: dict | None = None,
        duration_sec: int | None = None,
        simulation_time: str | None = None,
    ) -> SimulationCommand:
        return SimulationCommand(
            command_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            simulation_time=simulation_time,
            target_type=target_type.upper(),
            target_id=target_id,
            action=action.upper(),
            parameters=parameters or {},
            duration_sec=duration_sec,
            status="PENDING",
        )


def append_command(cmd: SimulationCommand) -> SimulationCommand:
    COMMANDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COMMANDS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(cmd)) + "\n")
    return cmd


def load_all_commands() -> list[SimulationCommand]:
    if not COMMANDS_PATH.exists():
        return []
    out: list[SimulationCommand] = []
    for line in COMMANDS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        out.append(SimulationCommand(**raw))
    return out


def rewrite_commands(commands: list[SimulationCommand]) -> None:
    with COMMANDS_PATH.open("w", encoding="utf-8") as f:
        for cmd in commands:
            f.write(json.dumps(asdict(cmd)) + "\n")


def clear_commands() -> None:
    if COMMANDS_PATH.exists():
        COMMANDS_PATH.write_text("", encoding="utf-8")


def cancel_command(command_id: str) -> SimulationCommand | None:
    cmds = load_all_commands()
    found = None
    for c in cmds:
        if c.command_id == command_id:
            if c.status in ("PENDING", "APPLIED"):
                c.status = "CANCELLED"
            found = c
            break
    if found:
        rewrite_commands(cmds)
    return found


def append_event_log(
    *,
    sim_now: datetime,
    kind: str,  # TEST | SIMULATION
    message: str,
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": sim_now.isoformat(),
        "kind": kind,
        "message": message,
        "target_type": target_type,
        "target_id": target_id,
    }
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def read_event_log(limit: int = 200) -> list[dict]:
    if not EVENT_LOG_PATH.exists():
        return []
    lines = [ln for ln in EVENT_LOG_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = [json.loads(ln) for ln in lines[-limit:]]
    return list(reversed(rows))


def clear_event_log() -> None:
    if EVENT_LOG_PATH.exists():
        EVENT_LOG_PATH.write_text("", encoding="utf-8")
