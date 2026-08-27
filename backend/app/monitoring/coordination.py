"""Small in-process generation guard coordinating monitoring with operational resets."""

from __future__ import annotations

from contextlib import contextmanager
import threading


class MonitoringResetCoordinator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._resetting = False

    def cycle_token(self) -> int | None:
        with self._lock:
            return None if self._resetting else self._generation

    @contextmanager
    def candidate_guard(self, token: int):
        """Serialize the short alert-write section with reset cleanup."""
        with self._lock:
            yield not self._resetting and token == self._generation

    @contextmanager
    def reset_guard(self):
        """Invalidate older cycles and block new alert writes until reset commits."""
        with self._lock:
            self._generation += 1
            self._resetting = True
            try:
                yield self._generation
            finally:
                self._resetting = False


monitoring_reset_coordinator = MonitoringResetCoordinator()
