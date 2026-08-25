"""API-boundary ID normalization. Domain services use integer DB keys only."""

from __future__ import annotations

import re

_SHIFT_RE = re.compile(r"^shift-(\d+)$")


def parse_shift_id(shift_id: str | int | None) -> int | None:
    """Convert frontend `shift-{db_id}` or raw int/string id to DB shift_id."""
    if shift_id is None:
        return None
    if isinstance(shift_id, int):
        return shift_id
    s = shift_id.strip()
    if not s:
        return None
    m = _SHIFT_RE.match(s)
    if m:
        return int(m.group(1))
    if s.isdigit():
        return int(s)
    return None


def format_shift_id(shift_id: int) -> str:
    """Frontend-facing synthetic shift identifier."""
    return f"shift-{shift_id}"
