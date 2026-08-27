"""Embedded simulation runner — tick loop owned by the FastAPI process.

Start / Pause / Resume from Simulation Centre write the control file;
this runner always ticks and the engine re-reads that file each cycle.
No separate `python -m simulator run` terminal is required.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.db.database import SessionLocal
from simulator.clock import get_sim_logger
from simulator.config import SimConfig
from simulator.control import patch_control_status, read_control, write_control
from simulator.engine import SimulationEngine

log = get_sim_logger()
_svc_log = logging.getLogger("minepulse.sim_service")


class SimulationService:
    """Singleton background tick loop sharing one engine instance."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._session = None
        self._engine: SimulationEngine | None = None
        self._last_error: str | None = None
        self._started_at: float | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def ensure_started(self) -> None:
        """Boot engine + background thread if not already running."""
        if self.running:
            return
        with self._lock:
            if self.running:
                return
            self._boot_engine()
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="minepulse-sim-ticks",
                daemon=True,
            )
            self._thread.start()
            self._started_at = time.time()
            _svc_log.info("Embedded simulator thread started")

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)
        self._thread = None
        with self._lock:
            self._close_engine()
        _svc_log.info("Embedded simulator stopped")

    def start_simulation(self) -> dict:
        self.ensure_started()
        with self._lock:
            if self._engine:
                self._engine.start()
            else:
                patch_control_status("RUNNING")
        return read_control()

    def pause_simulation(self) -> dict:
        with self._lock:
            if self._engine:
                self._engine.pause()
            else:
                patch_control_status("PAUSED")
        return read_control()

    def resume_simulation(self) -> dict:
        return self.start_simulation()

    def reset_simulation(self) -> dict:
        self.ensure_started()
        with self._lock:
            if not self._engine:
                self._boot_engine()
            assert self._engine is not None
            self._engine.reset()
            # Leave paused after reset so the operator presses Start
            self._engine.pause()
        return read_control()

    def activate_causal_scenario(
        self,
        scenario_id: str,
        target_id: str,
        *,
        duration_min: float | None = None,
        seed: int | None = None,
    ) -> dict:
        self.ensure_started()
        with self._lock:
            assert self._engine is not None
            return self._engine.activate_causal_scenario(
                scenario_id,
                target_id,
                duration_min=duration_min,
                seed=seed,
            )

    def stop_causal_scenario(self, run_id: str) -> dict:
        self.ensure_started()
        with self._lock:
            assert self._engine is not None
            return self._engine.stop_causal_scenario(run_id)

    def causal_scenario_status(self) -> list[dict]:
        self.ensure_started()
        with self._lock:
            assert self._engine is not None
            return self._engine.causal_scenarios.developer_status(include_hidden=True)

    def status_extra(self) -> dict[str, Any]:
        return {
            "embedded": True,
            "tick_thread_alive": self.running,
            "last_error": self._last_error,
        }

    def _boot_engine(self) -> None:
        self._close_engine()
        self._session = SessionLocal()
        try:
            self._engine = SimulationEngine(self._session)
            # Do not auto-start; honour control file (default STOPPED / PAUSED)
            control = read_control()
            status = control.get("status", "STOPPED")
            if status == "RUNNING":
                self._engine.clock.status = "RUNNING"
            else:
                self._engine.clock.status = "PAUSED" if status == "PAUSED" else "STOPPED"
            self._engine._persist_control()
            self._last_error = None
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._close_engine()
            _svc_log.error("Failed to boot simulation engine: %s", exc)
            raise

    def _close_engine(self) -> None:
        self._engine = None
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None

    def _loop(self) -> None:
        cfg = SimConfig()
        while not self._stop.is_set():
            t0 = time.monotonic()
            with self._lock:
                if self._engine is None:
                    try:
                        self._boot_engine()
                    except Exception as exc:  # noqa: BLE001
                        self._last_error = str(exc)
                if self._engine is not None:
                    try:
                        self._engine.tick()
                        self._last_error = None
                    except Exception as exc:  # noqa: BLE001
                        self._last_error = str(exc)
                        log.exception("Simulator tick failed: %s", exc)
                        # Recreate session after hard DB errors
                        try:
                            self._boot_engine()
                        except Exception:  # noqa: BLE001
                            pass
            elapsed = time.monotonic() - t0
            sleep_for = max(0.05, cfg.tick_seconds - elapsed)
            self._stop.wait(sleep_for)


_service: SimulationService | None = None


def get_simulation_service() -> SimulationService:
    global _service
    if _service is None:
        _service = SimulationService()
    return _service
