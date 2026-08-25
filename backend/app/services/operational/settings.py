"""Server-side operational configuration."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.operational_settings import OperationalSetting

_DEFAULTS = {
    "idle_alert_threshold_min": 15,
    "no_comm_threshold_min": 5,
    "cycle_duration_threshold_min": 50,
    "oem_online_sec": get_settings().oem_online_sec,
    "oem_disconnected_sec": get_settings().oem_disconnected_sec,
}


def _coerce(key: str, value) -> int | float:
    if key.endswith("_sec"):
        return float(value)
    return int(value)


def get_operational_settings(session: Session) -> dict[str, int | float]:
    out: dict[str, int | float] = dict(_DEFAULTS)
    rows = session.scalars(select(OperationalSetting)).all()
    for row in rows:
        if row.key in out:
            out[row.key] = _coerce(row.key, row.value)
    return out


def patch_operational_settings(session: Session, updates: dict[str, int | float]) -> dict[str, int | float]:
    allowed = set(_DEFAULTS.keys())
    for key, value in updates.items():
        if key not in allowed:
            continue
        row = session.scalar(select(OperationalSetting).where(OperationalSetting.key == key))
        if row:
            row.value = value
        else:
            session.add(OperationalSetting(key=key, value=value))
    session.commit()
    return get_operational_settings(session)
