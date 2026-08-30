"""Complete-file publication for simulator/API shared runtime snapshots.

Atomic replacement protects readers, not read/modify/write transactions. The
embedded runner serializes those transactions separately. One engine process
must own a runtime directory; running the CLI and embedded engine together is
not supported.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import time

_file_lock = threading.RLock()


class RuntimeFileError(RuntimeError):
    """A runtime file is unavailable/corrupt; never substitute simulated truth."""


def atomic_write_text(path: Path, content: str) -> None:
    # On Windows even read handles can briefly deny replacement. Serialize
    # embedded readers/writers as well as using atomic publication for processes.
    with _file_lock:
        _publish(path, content)


def _publish(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Close before replace: Windows cannot rename an open NamedTemporaryFile.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(3):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # A short-lived Windows reader/antivirus may hold the target.
                if attempt == 2:
                    raise
                time.sleep(0.01)
    except OSError as exc:
        raise RuntimeFileError(f"Cannot publish runtime file: {path.name}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json_object(path: Path) -> dict | None:
    """Missing is distinct from corrupt. Retry only transient read/parse errors."""
    with _file_lock:
        return _read_json_object(path)


def _read_json_object(path: Path) -> dict | None:
    for attempt in range(3):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            return data
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            if attempt == 2:
                raise RuntimeFileError(f"Cannot read runtime file: {path.name}") from exc
            time.sleep(0.01)
    raise AssertionError("unreachable")
