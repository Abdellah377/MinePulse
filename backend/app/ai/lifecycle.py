"""In-process investigation identity, reuse, and concurrency gates."""

from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session

from app.ai.contracts import InvestigationResult, InvestigationStatus, InvestigationTrigger
from app.ai.persistence import find_investigations, record_to_result
from app.db.models import AiInvestigation

logger = logging.getLogger(__name__)

_REUSABLE_STATUSES = {
    InvestigationStatus.COMPLETED,
    InvestigationStatus.COMPLETED_WITH_UNCERTAINTY,
    InvestigationStatus.PENDING,
    InvestigationStatus.RESOLVING_CONTEXT,
    InvestigationStatus.GATHERING_EVIDENCE,
    InvestigationStatus.ANALYZING,
    InvestigationStatus.BUILDING_CONCLUSION,
    InvestigationStatus.BUILDING_RECOMMENDATION,
}


class InvestigationExecutionGate:
    """Serialize one alert and bound simultaneous LLM investigations."""

    def __init__(self) -> None:
        self._meta = threading.Lock()
        self._scope_locks: dict[str, threading.Lock] = {}
        self._semaphore: threading.Semaphore | None = None
        self._limit: int | None = None
        self._in_flight = 0
        self._in_flight_lock = threading.Lock()
        self.max_observed_concurrency = 0

    def reset_for_tests(self) -> None:
        with self._meta:
            self._scope_locks.clear()
            self._semaphore = None
            self._limit = None
        with self._in_flight_lock:
            self._in_flight = 0
            self.max_observed_concurrency = 0

    def scope_lock(self, site_id: int, source_record_id: str | None) -> threading.Lock:
        key = f"{site_id}:{source_record_id or '-'}"
        with self._meta:
            lock = self._scope_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._scope_locks[key] = lock
            return lock

    def semaphore(self, limit: int) -> threading.Semaphore:
        safe_limit = max(1, limit)
        with self._meta:
            if self._semaphore is None or self._limit != safe_limit:
                self._semaphore = threading.Semaphore(safe_limit)
                self._limit = safe_limit
            return self._semaphore

    def mark_enter(self) -> None:
        with self._in_flight_lock:
            self._in_flight += 1
            if self._in_flight > self.max_observed_concurrency:
                self.max_observed_concurrency = self._in_flight

    def mark_leave(self) -> None:
        with self._in_flight_lock:
            self._in_flight = max(0, self._in_flight - 1)


investigation_gate = InvestigationExecutionGate()


def latest_investigation(session: Session, trigger: InvestigationTrigger) -> AiInvestigation | None:
    if not trigger.source_record_id:
        return None
    rows = find_investigations(
        session,
        site_id=trigger.site_id,
        source_record_id=trigger.source_record_id,
        shift_id=trigger.shift_id,
    )
    return rows[0] if rows else None


def reusable_investigation(row: AiInvestigation | None) -> InvestigationResult | None:
    """Return a durable non-FAILED result instead of starting a parallel run."""
    if row is None:
        return None
    try:
        status = InvestigationStatus(row.status)
    except ValueError:
        return None
    if status == InvestigationStatus.FAILED:
        return None
    if status in _REUSABLE_STATUSES:
        return record_to_result(row)
    return None
