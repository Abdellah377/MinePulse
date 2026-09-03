"""RCA constraint hierarchy. LLM hypotheses never become hard feasibility constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.enums import EquipmentType

_LOADER_TYPES = {EquipmentType.EXCAVATOR, EquipmentType.LOADER, "EXCAVATOR", "LOADER"}
_CONFIRMED = {"CONFIRMED"}
_PROBABLE = {"PROBABLE"}


@dataclass(frozen=True)
class RcaGateResult:
    hard_exclude_loader_ids: set[int] = field(default_factory=set)
    caution_notes: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


def _type_value(equipment_type: Any) -> str | None:
    if equipment_type is None:
        return None
    if hasattr(equipment_type, "value"):
        return str(equipment_type.value)
    return str(equipment_type)


def _is_loader_type(equipment_type: Any) -> bool:
    if equipment_type in _LOADER_TYPES:
        return True
    return _type_value(equipment_type) in {"EXCAVATOR", "LOADER"}


def rca_constraints(
    *,
    diagnosis_status: str | None,
    reliable_root_cause: bool,
    equipment_id: int | None,
    equipment_type: Any,
    supported_hypothesis_ids: list[str] | None = None,
) -> RcaGateResult:
    status = str(getattr(diagnosis_status, "value", diagnosis_status) or "").upper()
    hypotheses = [str(item) for item in (supported_hypothesis_ids or []) if item]
    if status in _CONFIRMED and reliable_root_cause and equipment_id is not None and _is_loader_type(equipment_type):
        return RcaGateResult(hard_exclude_loader_ids={int(equipment_id)}, evidence_ids=hypotheses)
    if status in _PROBABLE:
        note = "Diagnostic probable — à traiter comme prudence opérateur, pas comme exclusion dure."
        return RcaGateResult(caution_notes=[note], evidence_ids=hypotheses)
    return RcaGateResult(evidence_ids=hypotheses)


def apply_rca_excludes(candidates: list[dict], hard_exclude_loader_ids: set[int]) -> list[dict]:
    if not hard_exclude_loader_ids:
        return list(candidates)
    return [row for row in candidates if row.get("loaderId") not in hard_exclude_loader_ids]
