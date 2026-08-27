from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.ai.contracts import InvestigationStatus, Severity, TriggerSource, TriggerType
from app.config import Settings
from app.db.enums import AlertStatus
from app.db.models import AiInvestigation, Alert, Site
from app.monitoring.contracts import MonitoringCandidate
from app.monitoring.scheduler import MonitoringScheduler
from app.monitoring.coordination import monitoring_reset_coordinator
from app.monitoring.service import MonitoringService, _coalesce_existing_alert_findings

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _settings(**overrides):
    values = {
        "monitoring_enabled": True,
        "monitoring_investigation_cooldown_minutes": 15,
        "monitoring_interval_seconds": 5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _candidate(*, severity=Severity.WARNING):
    return MonitoringCandidate(
        detector_id="unit-detector",
        trigger_type=TriggerType.EQUIPMENT_ANOMALY,
        site_id=1,
        shift_id=2,
        equipment_id=10,
        detected_at=NOW,
        severity=severity,
        title="Operational symptom",
        reason="TRK-010 has remained stopped for 4 minutes.",
        metric="stop_duration",
        value=4,
        threshold=2,
        unit="min",
        deduplication_key="unit:1:10",
    )


class FakeSession:
    def __init__(self):
        self.alerts: dict[int, Alert] = {}
        self.investigations: dict[object, object] = {}
        self.next_id = 1

    def add(self, obj):
        if isinstance(obj, Alert):
            if obj.alert_id is None:
                obj.alert_id = self.next_id
                self.next_id += 1
            self.alerts[obj.alert_id] = obj

    def get(self, model, pk):
        if model is Alert:
            return self.alerts.get(pk)
        if model is AiInvestigation:
            return self.investigations.get(pk)
        return None

    def delete(self, obj):
        if isinstance(obj, Alert):
            self.alerts.pop(obj.alert_id, None)
        else:
            investigation_id = getattr(obj, "investigation_id", None)
            self.investigations.pop(investigation_id, None)

    def commit(self):
        pass

    def refresh(self, obj):
        pass

    def rollback(self):
        pass

    def scalar(self, statement):
        return None


def test_candidate_builds_automatic_trigger_and_deduplicates_second_attempt(monkeypatch):
    session = FakeSession()
    captured = []

    def runner(_session, trigger):
        captured.append(trigger)
        return SimpleNamespace(
            investigation_id=uuid4(), status=InvestigationStatus.COMPLETED,
            completed_at=NOW,
        )

    monkeypatch.setattr(
        "app.monitoring.service.list_site_alerts",
        lambda _session, _site_id, limit=500, active_only=True: [
            alert for alert in session.alerts.values() if alert.status != AlertStatus.RESOLVED
        ],
    )
    service = MonitoringService(settings=_settings(), investigation_runner=runner)
    assert service._process_candidate(session, _candidate()) is True
    assert service._process_candidate(session, _candidate()) is False
    assert len(captured) == 1
    trigger = captured[0]
    assert trigger.trigger_source == TriggerSource.AUTOMATIC_MONITORING
    assert trigger.source_record_id == "alert-1"
    assert trigger.payload["reason"].startswith("TRK-010")
    assert session.alerts[1].source.value == "RULE"


def test_linked_authoritative_alert_wins_over_derived_duplicate():
    derived = _candidate()
    linked = derived.model_copy(update={"source_alert_id": 99, "deduplication_key": "critical-alert:99"})
    assert _coalesce_existing_alert_findings([derived, linked]) == [linked]


def test_severity_escalation_bypasses_cooldown(monkeypatch):
    session = FakeSession()
    calls = []
    monkeypatch.setattr(
        "app.monitoring.service.list_site_alerts",
        lambda *_args, **_kwargs: list(session.alerts.values()),
    )
    runner = lambda _session, trigger: (
        calls.append(trigger) or SimpleNamespace(
            investigation_id=uuid4(), status=InvestigationStatus.COMPLETED, completed_at=NOW
        )
    )
    service = MonitoringService(settings=_settings(), investigation_runner=runner)
    service._process_candidate(session, _candidate(severity=Severity.WARNING))
    service._process_candidate(session, _candidate(severity=Severity.CRITICAL))
    assert len(calls) == 2
    assert session.alerts[1].severity.value == "CRITICAL"


def test_expired_cooldown_allows_retrigger(monkeypatch):
    session = FakeSession()
    calls = []
    monkeypatch.setattr("app.monitoring.service.list_site_alerts", lambda *_args, **_kwargs: list(session.alerts.values()))
    runner = lambda _session, trigger: (
        calls.append(trigger) or SimpleNamespace(
            investigation_id=uuid4(), status=InvestigationStatus.COMPLETED, completed_at=trigger.occurred_at
        )
    )
    service = MonitoringService(settings=_settings(), investigation_runner=runner)
    service._process_candidate(session, _candidate())
    later = _candidate().model_copy(update={"detected_at": NOW + timedelta(minutes=16)})
    service._process_candidate(session, later)
    assert len(calls) == 2


def test_detector_failure_isolated_and_other_detector_continues(monkeypatch):
    site = Site(site_id=1, code="S", name="Site", active=True)
    snapshot = object()
    processed = []

    class Scalars:
        def all(self):
            return [site]

    class CycleSession(FakeSession):
        def scalars(self, _statement):
            return Scalars()

    def broken(_snapshot, _settings):
        raise RuntimeError("detector bug")

    def healthy(_snapshot, _settings):
        return [_candidate()]

    service = MonitoringService(
        settings=_settings(), detectors=(broken, healthy), snapshot_builder=lambda *_: snapshot
    )
    monkeypatch.setattr(
        service,
        "_process_candidate",
        lambda _session, candidate, **_kwargs: processed.append(candidate) or True,
    )
    counts = service.run_cycle(CycleSession())
    assert counts["errors"] == 1
    assert counts["investigations"] == 1
    assert len(processed) == 1


def test_investigation_failure_is_logged_and_cycle_remains_controlled(monkeypatch):
    site = Site(site_id=1, code="S", name="Site", active=True)
    session = FakeSession()

    class Scalars:
        def all(self):
            return [site]

    session.scalars = lambda _statement: Scalars()
    monkeypatch.setattr(
        "app.monitoring.service.list_site_alerts",
        lambda *_args, **_kwargs: list(session.alerts.values()),
    )
    service = MonitoringService(
        settings=_settings(),
        detectors=(lambda *_: [_candidate()],),
        snapshot_builder=lambda *_: object(),
        investigation_runner=lambda *_: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    counts = service.run_cycle(session)
    assert counts["errors"] == 1
    assert counts["investigations"] == 0
    assert counts["deduplicated"] == 0
    monitoring = session.alerts[1].metadata_["monitoring"]
    assert monitoring["lastInvestigationErrorType"] == "RuntimeError"
    assert "provider unavailable" not in str(monitoring)


def test_monitoring_disabled_does_not_query_or_invoke():
    class NoTouchSession:
        def scalars(self, _statement):
            raise AssertionError("disabled monitoring queried the database")

    counts = MonitoringService(settings=_settings(monitoring_enabled=False)).run_cycle(NoTouchSession())
    assert counts == {"sites": 0, "candidates": 0, "investigations": 0, "deduplicated": 0, "errors": 0}


def test_scheduler_start_is_idempotent_and_stops_cleanly():
    calls = []

    async def exercise():
        scheduler = MonitoringScheduler(settings=_settings(), cycle_runner=lambda: calls.append(1) or {})
        await scheduler.start()
        first_task = scheduler._task
        await scheduler.start()
        assert scheduler._task is first_task
        await asyncio.sleep(0.05)
        await scheduler.stop()
        assert not scheduler.running

    asyncio.run(exercise())
    assert len(calls) == 1


def test_monitoring_package_has_no_simulator_imports():
    root = Path(__file__).resolve().parents[1] / "app" / "monitoring"
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            imported = ([module] if module else []) + names
            if any(name == "simulator" or name.startswith("simulator.") for name in imported):
                violations.append(str(path))
    assert violations == []


def test_candidate_from_pre_reset_generation_cannot_recreate_alert(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        "app.monitoring.service.list_site_alerts",
        lambda *_args, **_kwargs: list(session.alerts.values()),
    )
    stale_generation = monitoring_reset_coordinator.cycle_token()
    assert stale_generation is not None
    with monitoring_reset_coordinator.reset_guard():
        pass

    service = MonitoringService(
        settings=_settings(),
        investigation_runner=lambda *_: (_ for _ in ()).throw(
            AssertionError("stale candidate reached LangGraph")
        ),
    )
    assert service._process_candidate(
        session, _candidate(), generation=stale_generation
    ) is False
    assert session.alerts == {}


def test_inflight_investigation_finishing_after_reset_is_discarded(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        "app.monitoring.service.list_site_alerts",
        lambda *_args, **_kwargs: list(session.alerts.values()),
    )

    def runner(_session, _trigger):
        investigation_id = uuid4()
        # Reset wins while the provider/graph is in flight: persisted alerts
        # are cleaned, then a late graph result arrives from the old generation.
        with monitoring_reset_coordinator.reset_guard():
            session.alerts.clear()
        row = SimpleNamespace(investigation_id=investigation_id)
        session.investigations[investigation_id] = row
        return SimpleNamespace(
            investigation_id=investigation_id,
            status=InvestigationStatus.COMPLETED,
            completed_at=NOW,
        )

    service = MonitoringService(settings=_settings(), investigation_runner=runner)
    assert service._process_candidate(session, _candidate()) is False
    assert session.alerts == {}
    assert session.investigations == {}
