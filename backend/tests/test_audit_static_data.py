"""Auditor classifies unguarded 0.94 as INVALID — nearby useApiMode is not a guard."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_AUDIT = Path(__file__).resolve().parents[1] / "scripts" / "audit_static_data.py"
_spec = importlib.util.spec_from_file_location("audit_static_data", _AUDIT)
assert _spec and _spec.loader
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def _classify(text: str, line_no: int, label: str = "tonnage heuristic 0.94") -> str:
    path = Path("src/components/equipment/EquipmentDetailContent.tsx")
    lines = text.splitlines()
    line_text = lines[line_no - 1]
    col = line_text.find("0.94")
    if col < 0:
        col = None
    return audit.classify(path, label, line_text, text, line_no, col)


def test_unguarded_094_is_invalid():
    text = """
export function EquipmentDetailContent() {
  const x = 1
  const tonnageHauled = eq.capacityTons * eq.tripsThisShift * 0.94
  return tonnageHauled
}
""".strip()
    kind = _classify(text, 3)
    assert kind == "INVALID_OPERATIONAL_HARDCODE"


def test_useapi_fourteen_lines_above_does_not_guard_094():
    """FAIL 20 fixture: maintenance fetch uses useApiMode well above the heuristic."""
    lines = [
        "export function EquipmentDetailContent() {",
        "  useEffect(() => {",
        "    if (!useApiMode) {",
        "      setMaintenanceRows(null)",
        "      return",
        "    }",
        "    void fetchEquipmentDetail(equipmentId)",
        "  }, [equipmentId])",
        "  const eq = equipment.find((e) => e.id === equipmentId)",
        "  if (!eq) return null",
        "  const cfg = STATE_CONFIG[eq.state]",
        "  const now = rangeEnd",
        "  const shiftElapsedMin = Math.max(1, (rangeEnd - rangeStart) / 60_000)",
        "  const waitingPct = (eq.waitingMinutesThisShift / shiftElapsedMin) * 100",
        "  const idlePct = (eq.idleMinutesThisShift / shiftElapsedMin) * 100",
        "  const tonnageHauled = eq.capacityTons * eq.tripsThisShift * 0.94",
        "  return tonnageHauled",
        "}",
    ]
    text = "\n".join(lines)
    kind = _classify(text, 16)
    assert kind == "INVALID_OPERATIONAL_HARDCODE"


def test_094_inside_not_useapi_block_is_guarded():
    text = """
export function equipmentContributionTons(eq) {
  if (!useApiMode) {
    return eq.capacityTons * eq.tripsThisShift * 0.94
  }
  return null
}
""".strip()
    kind = _classify(text, 3)
    assert kind == "MOCK_GUARDED"


def test_no_jsx_mock_else_window():
    assert not hasattr(audit, "_in_jsx_mock_else")
    assert not hasattr(audit, "_same_line_ternary_false_arm")


def test_094_in_useapi_true_arm_is_invalid():
    text = "const t = useApiMode ? eq.capacityTons * eq.tripsThisShift * 0.94 : 0"
    kind = _classify(text, 1)
    assert kind == "INVALID_OPERATIONAL_HARDCODE"


def test_094_in_useapi_false_arm_is_guarded():
    text = "const t = useApiMode ? null : eq.capacityTons * eq.tripsThisShift * 0.94"
    kind = _classify(text, 1)
    assert kind == "MOCK_GUARDED"
