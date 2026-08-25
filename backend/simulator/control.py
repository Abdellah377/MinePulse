"""Simulation control file I/O — shared by CLI engine and FastAPI (no Engine boot)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent
SIM_STATE_PATH = SIM_DIR / "sim_state.json"
COMMANDS_PATH = SIM_DIR / "sim_commands.jsonl"
RUNTIME_SNAPSHOT_PATH = SIM_DIR / "sim_runtime.json"
EVENT_LOG_PATH = SIM_DIR / "sim_event_log.jsonl"
HEARTBEAT_PATH = SIM_DIR / "sim_heartbeat.json"
CHECKPOINTS_DIR = SIM_DIR / "checkpoints"

VALID_SPEEDS = (1, 5, 10, 30, 60, 120)
VALID_MODES = ("NORMAL", "MANUAL", "STRESS", "SCENARIO", "REPLAY")


def default_control() -> dict:
    return {
        "status": "STOPPED",
        "speed": 30,
        "seed": 42,
        "mode": "MANUAL",
        "scenario": "normal",
        "sim_now": datetime(2026, 1, 29, 6, 0, 0, tzinfo=timezone.utc).isoformat(),
        "wall_started_at": None,
        "wall_elapsed_sec": 0.0,
        "note": "Simulateur intégré à l'API — contrôlez depuis le Centre de simulation.",
    }


def read_control() -> dict:
    if SIM_STATE_PATH.exists():
        data = json.loads(SIM_STATE_PATH.read_text(encoding="utf-8"))
        base = default_control()
        base.update(data)
        return base
    return default_control()


def write_control(data: dict) -> dict:
    """Merge into existing control and write. Returns merged dict."""
    current = read_control()
    current.update(data)
    # Preserve sim_now unless explicitly provided
    SIM_STATE_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def update_control(**kwargs) -> dict:
    return write_control(kwargs)


def patch_control_status(status: str) -> dict:
    return update_control(status=status)


def patch_control_speed(speed: float) -> dict:
    if int(speed) not in VALID_SPEEDS:
        raise ValueError(f"speed must be one of {VALID_SPEEDS}")
    return update_control(speed=float(speed))


def patch_control_mode(mode: str) -> dict:
    mode = mode.upper()
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}")
    return update_control(mode=mode)


def write_heartbeat(sim_now: datetime, tick: int, status: str) -> None:
    HEARTBEAT_PATH.write_text(
        json.dumps({"ts": sim_now.isoformat(), "tick": tick, "status": status}),
        encoding="utf-8",
    )


def read_heartbeat() -> dict | None:
    if not HEARTBEAT_PATH.exists():
        return None
    try:
        return json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
