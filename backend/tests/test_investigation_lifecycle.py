from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.ai.contracts import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTrigger,
    TriggerSource,
    TriggerType,
)
from app.ai.lifecycle import investigation_gate
from app.ai.service import run_investigation


NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


def _trigger(*, source_record_id="alert-1"):
    return InvestigationTrigger(
        site_id=1,
        shift_id=2,
        trigger_type=TriggerType.CONGESTION_RISK,
        trigger_source=TriggerSource.USER_INVESTIGATE,
        source="alertes-ui",
        source_record_id=source_record_id,
    )


def _result(*, status=InvestigationStatus.COMPLETED, investigation_id=None):
    return InvestigationResult(
        investigation_id=investigation_id or uuid4(),
        trigger=_trigger(),
        max_iterations=1,
        status=status,
        started_at=NOW,
        completed_at=NOW,
        graph_version="test",
        provider="mock",
        model="mock",
        evidence=[],
    )


def _patch_service(monkeypatch, **overrides):
    investigation_gate.reset_for_tests()
    monkeypatch.setattr("app.ai.service.verify_investigation_storage", lambda *_: None)
    monkeypatch.setattr("app.ai.service.validate_trigger_scope", lambda *_: None)
    monkeypatch.setattr(
        "app.ai.service.get_settings",
        lambda: SimpleNamespace(
            ai_max_investigation_iterations=1,
            ai_investigation_max_concurrent=2,
            ai_debug_mode=False,
        ),
    )
    monkeypatch.setattr("app.ai.service.latest_investigation", lambda *_: None)
    for name, value in overrides.items():
        monkeypatch.setattr(f"app.ai.service.{name}", value)


def test_completed_investigation_is_reused_without_provider(monkeypatch):
    existing = _result()
    invoked = []
    _patch_service(
        monkeypatch,
        latest_investigation=lambda *_: SimpleNamespace(status="COMPLETED"),
        reusable_investigation=lambda *_: existing,
        _invoke_investigation_graph=lambda *_a, **_k: invoked.append(1) or existing,
        create_llm_provider=lambda *_: (_ for _ in ()).throw(AssertionError("provider constructed")),
    )
    result = run_investigation(object(), _trigger(), provider=SimpleNamespace())
    assert result.investigation_id == existing.investigation_id
    assert invoked == []


def test_failed_investigation_retry_starts_a_new_run(monkeypatch):
    previous = SimpleNamespace(status="FAILED")
    fresh = _result(investigation_id=uuid4())
    invoked = []
    _patch_service(
        monkeypatch,
        latest_investigation=lambda *_: previous,
        reusable_investigation=lambda *_: None,
        _invoke_investigation_graph=lambda *_a, **_k: invoked.append(1) or fresh,
    )
    result = run_investigation(object(), _trigger(), provider=SimpleNamespace(provider_name="mock", model_name="mock"))
    assert invoked == [1]
    assert result.investigation_id == fresh.investigation_id
    assert result.investigation_id != getattr(previous, "investigation_id", None)


def test_double_start_reuses_the_first_completed_result(monkeypatch):
    created = []

    def invoke(*_a, **_k):
        created.append(1)
        time.sleep(0.05)
        return _result()

    _patch_service(monkeypatch, _invoke_investigation_graph=invoke)
    first = run_investigation(object(), _trigger(), provider=SimpleNamespace())
    _patch_service(
        monkeypatch,
        latest_investigation=lambda *_: SimpleNamespace(status="COMPLETED"),
        reusable_investigation=lambda *_: first,
        _invoke_investigation_graph=lambda *_a, **_k: created.append(2) or first,
    )
    second = run_investigation(object(), _trigger(), provider=SimpleNamespace())
    assert created == [1]
    assert second.investigation_id == first.investigation_id


def test_provider_concurrency_stays_within_configured_bound(monkeypatch):
    _patch_service(monkeypatch)

    def invoke(*_a, **_k):
        time.sleep(0.2)
        return _result()

    monkeypatch.setattr("app.ai.service._invoke_investigation_graph", invoke)
    errors = []

    def worker(index: int) -> None:
        try:
            run_investigation(
                object(),
                _trigger(source_record_id=f"alert-{index}"),
                provider=SimpleNamespace(),
            )
        except Exception as exc:  # pragma: no cover - test failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert investigation_gate.max_observed_concurrency <= 2
    assert investigation_gate.max_observed_concurrency >= 1
