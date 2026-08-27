"""In-process FastAPI monitoring loop; LangGraph itself never polls or sleeps."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.config import Settings, get_settings
from app.monitoring.service import run_monitoring_cycle

logger = logging.getLogger(__name__)


class MonitoringScheduler:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        cycle_runner: Callable[[], dict[str, int]] = run_monitoring_cycle,
    ) -> None:
        self.settings = settings or get_settings()
        self.cycle_runner = cycle_runner
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self.settings.monitoring_enabled:
            logger.info("Operational monitoring disabled by configuration")
            return
        if self.running:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="minepulse-operational-monitor")
        logger.info("Operational monitoring scheduler started")

    async def stop(self) -> None:
        if self._task is None:
            return
        assert self._stop is not None
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=max(5.0, self.settings.monitoring_interval_seconds + 1.0))
        except asyncio.TimeoutError:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        finally:
            self._task = None
            self._stop = None
        logger.info("Operational monitoring scheduler stopped")

    async def _run(self) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.cycle_runner)
            except Exception:
                logger.exception("Monitoring cycle crashed; scheduler will continue")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.monitoring_interval_seconds)
            except asyncio.TimeoutError:
                pass


_scheduler: MonitoringScheduler | None = None


def get_monitoring_scheduler() -> MonitoringScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = MonitoringScheduler()
    return _scheduler
