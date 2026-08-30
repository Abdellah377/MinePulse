"""Simulation command queue — JSONL pending commands for the tick process."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import threading

from simulator.control import COMMANDS_PATH, EVENT_LOG_PATH
from simulator.file_io import RuntimeFileError, atomic_write_text

_command_lock = threading.RLock()


@contextmanager
def command_transaction():
    """Serialize embedded API mutations with a complete engine command cycle."""
    with _command_lock:
        yield


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


@command_transaction()
def append_command(cmd: SimulationCommand) -> SimulationCommand:
    commands = load_all_commands()
    commands.append(cmd)
    rewrite_commands(commands)
    return cmd


@command_transaction()
def load_all_commands() -> list[SimulationCommand]:
    if not COMMANDS_PATH.exists():
        return []
    out: list[SimulationCommand] = []
    for line in COMMANDS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            out.append(SimulationCommand(**raw))
        except (ValueError, TypeError) as exc:
            raise RuntimeFileError("Invalid simulation command queue") from exc
    return out


@command_transaction()
def rewrite_commands(commands: list[SimulationCommand]) -> None:
    atomic_write_text(COMMANDS_PATH, "".join(json.dumps(asdict(cmd)) + "\n" for cmd in commands))


@command_transaction()
def clear_commands() -> None:
    atomic_write_text(COMMANDS_PATH, "")


@command_transaction()
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


@command_transaction()
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


@command_transaction()
def read_event_log(limit: int = 200) -> list[dict]:
    if not EVENT_LOG_PATH.exists():
        return []
    lines = [ln for ln in EVENT_LOG_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    try:
        rows = [json.loads(ln) for ln in lines[-limit:]]
    except ValueError as exc:
        raise RuntimeFileError("Invalid simulation event log") from exc
    return list(reversed(rows))


@command_transaction()
def clear_event_log() -> None:
    atomic_write_text(EVENT_LOG_PATH, "")
