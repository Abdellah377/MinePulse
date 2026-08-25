#!/usr/bin/env python3
"""Scan frontend for INVALID_OPERATIONAL_HARDCODE outside mock-guarded blocks.

A line is MOCK_GUARDED only if it is in:
  - a mock-only file (src/lib/mock/**)
  - a test file (*.test.ts / *.test.tsx)
  - the mock arm of `if (!useApiMode) { ... }`
  - after `if (useApiMode) return/throw` at the same function body
  - the false arm of a ternary `useApiMode ? api : mock`

A nearby mention of useApiMode is NOT a mock guard.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

MOCK_PATH_MARKERS = ("/mock/", "lib/mock/")

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("MERAH narrative", re.compile(r"MERAH_SHIFT_SCENARIO")),
    ("scenario targetTons", re.compile(r"scenario\.targetTons")),
    ("demo target 8160", re.compile(r"\b8160\b")),
    ("demo site MP-SIM-01", re.compile(r"MP-SIM-01")),
    ("demo shift-morning", re.compile(r"shift-morning")),
    ("fuel heuristic 0.88", re.compile(r"capacityTons\s*\*\s*0\.88")),
    ("fuel heuristic 0.85", re.compile(r"capacityTons\s*\*\s*\(\s*0\.85|0\.85\s*\+\s*Math\.random")),
    ("tonnage heuristic 0.94", re.compile(r"\*\s*0\.94|\b0\.94\b")),
    ("cycle guess 480/", re.compile(r"480\s*/")),
    ("hardcoded shift 06:00", re.compile(r"setHours\(\s*6\s*,")),
]


def _in_mock_file(rel: str) -> bool:
    return any(m in rel for m in MOCK_PATH_MARKERS)


def _is_test_file(rel: str) -> bool:
    return rel.endswith(".test.ts") or rel.endswith(".test.tsx")


def _function_start(lines: list[str], line_no: int) -> int:
    """Return 1-based line of containing top-level function declaration."""
    for i in range(line_no - 1, -1, -1):
        line = lines[i]
        if re.search(r"^\s*(export\s+)?(async\s+)?function\s+\w+", line):
            return i + 1
    return 1


def _in_not_useapi_block(lines: list[str], line_no: int) -> bool:
    """True if line_no is inside `if (!useApiMode) { ... }` via brace matching."""
    depth = 0
    for i in range(line_no - 2, -1, -1):
        line = lines[i]
        for ch in reversed(line):
            if ch == "}":
                depth += 1
            elif ch == "{":
                if depth > 0:
                    depth -= 1
                else:
                    if re.search(r"if\s*\(\s*!useApiMode\s*\)", line):
                        return True
                    if i > 0 and re.search(r"if\s*\(\s*!useApiMode\s*\)", lines[i - 1]):
                        return True
    return False


def _after_use_api_early_return(lines: list[str], line_no: int) -> bool:
    """True when the line is after a function-body `if (useApiMode) return/throw`."""
    fn_idx = _function_start(lines, line_no) - 1
    depth = 0
    body_depth: int | None = None
    i = fn_idx
    while i < line_no - 1:
        line = lines[i]
        if body_depth is None:
            opens = line.count("{")
            closes = line.count("}")
            if opens:
                depth += opens
                body_depth = depth
                depth -= closes
            i += 1
            continue
        if depth == body_depth:
            if re.search(r"if\s*\(\s*useApiMode\s*\)\s*(return|throw)\b", line):
                return True
            if re.search(r"if\s*\(\s*useApiMode\s*\)\s*\{", line):
                block_depth = 0
                has_exit = False
                j = i
                while j < line_no - 1:
                    cur = lines[j]
                    if j == i:
                        after = cur.split("{", 1)
                        chunk = after[1] if len(after) > 1 else ""
                        block_depth = 1 + chunk.count("{") - chunk.count("}")
                    else:
                        block_depth += cur.count("{") - cur.count("}")
                    if re.search(r"\b(return|throw)\b", cur):
                        has_exit = True
                    if block_depth <= 0:
                        return has_exit
                    j += 1
                return False
        depth += line.count("{") - line.count("}")
        i += 1
    return False


def _in_useapi_ternary_false_arm(lines: list[str], line_no: int, col: int | None = None) -> bool:
    """True if the match position is in the false arm of `useApiMode ? api : mock`.

    Uses text up to the match column so `useApiMode ? 0.94 : 1` is NOT guarded.
    """
    prefix = lines[: max(0, line_no - 1)]
    current = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
    if col is None:
        blob = "\n".join(prefix + [current])
    else:
        blob = "\n".join(prefix + [current[:col]])
    i = 0
    n = len(blob)
    depth = 0
    stack: list[dict] = []

    def skip_ws(p: int) -> int:
        while p < n and blob[p] in " \t\n\r":
            p += 1
        return p

    while i < n:
        if blob.startswith("useApiMode", i) and (i == 0 or not (blob[i - 1].isalnum() or blob[i - 1] == "_")):
            j = skip_ws(i + len("useApiMode"))
            if j < n and blob[j] == "?" and not (j + 1 < n and blob[j + 1] in ".?"):
                stack.append({"depth": depth, "nested_q": 0, "phase": "q"})
                i = j + 1
                continue
        if i + 1 < n and blob[i : i + 2] in ("?.", "??"):
            i += 2
            continue
        c = blob[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            while stack and stack[-1]["depth"] > depth:
                stack.pop()
        elif c == "?" and not (i + 1 < n and blob[i + 1] in ".?"):
            for t in reversed(stack):
                if t["depth"] == depth and t["phase"] == "q":
                    t["nested_q"] += 1
                    break
        elif c == ":":
            for t in reversed(stack):
                if t["depth"] == depth and t["phase"] == "q":
                    if t["nested_q"] > 0:
                        t["nested_q"] -= 1
                    else:
                        t["phase"] = "false"
                    break
        i += 1
    return any(t["phase"] == "false" for t in stack)


def line_mock_guarded(lines: list[str], line_no: int, col: int | None = None) -> bool:
    if _in_not_useapi_block(lines, line_no):
        return True
    if _after_use_api_early_return(lines, line_no):
        return True
    if _in_useapi_ternary_false_arm(lines, line_no, col):
        return True
    return False


def _all_merah_usages_guarded(lines: list[str]) -> bool:
    for i, line in enumerate(lines, start=1):
        if "MERAH_SHIFT_SCENARIO" not in line:
            continue
        if "import" in line:
            continue
        col = line.find("MERAH_SHIFT_SCENARIO")
        if not line_mock_guarded(lines, i, col if col >= 0 else None):
            return False
    return True


def classify(
    path: Path,
    label: str,
    line_text: str,
    file_text: str,
    line_no: int,
    col: int | None = None,
) -> str:
    rel = path.as_posix().replace("\\", "/")
    lines = file_text.splitlines()

    if _in_mock_file(rel):
        return "MOCK_FILE"

    if _is_test_file(rel):
        return "TEST_FILE"

    if label == "MERAH narrative" and "import" in line_text:
        if _all_merah_usages_guarded(lines):
            return "MOCK_GUARDED"
        return "INVALID_OPERATIONAL_HARDCODE"

    if line_mock_guarded(lines, line_no, col):
        return "MOCK_GUARDED"

    return "INVALID_OPERATIONAL_HARDCODE"


def scan() -> list[dict]:
    findings: list[dict] = []
    for path in SRC.rglob("*"):
        if path.suffix not in (".ts", ".tsx"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for label, pattern in PATTERNS:
            for m in pattern.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                line_start = text.rfind("\n", 0, m.start()) + 1
                col = m.start() - line_start
                line_text = lines[line_no - 1] if line_no <= len(lines) else ""
                kind = classify(path, label, line_text, text, line_no, col)
                findings.append(
                    {
                        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                        "line": line_no,
                        "label": label,
                        "kind": kind,
                    }
                )
    return findings


def main() -> int:
    findings = scan()
    invalid = [f for f in findings if f["kind"] == "INVALID_OPERATIONAL_HARDCODE"]
    print(f"Scanned {SRC}")
    print(f"Total findings: {len(findings)}")
    print(f"INVALID_OPERATIONAL_HARDCODE: {len(invalid)}")
    for f in sorted(invalid, key=lambda x: (x["file"], x["line"])):
        print(f"  [{f['kind']}] {f['file']}:{f['line']} — {f['label']}")
    if not invalid:
        print("PASS — no INVALID_OPERATIONAL_HARDCODE outside classified exceptions")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
