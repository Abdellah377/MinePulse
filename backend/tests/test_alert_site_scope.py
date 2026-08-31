"""Cross-site alert access for Actions IA and optimization."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.db.enums import AlertSeverity, AlertSource, AlertStatus, EquipmentType
from app.db.models import Alert, Equipment, Site, Zone
from app.optimization.inbox import inbox_detail
from app.optimization.service import create_optimization_run, list_optimization_runs
from app.services.operational.alerts import _site_scope, get_site_alert_or_404
from app.services.operational.context import OperationalContext
from sqlalchemy import select


SITE_ID = 17
OTHER_SITE = 99


def _alert(**overrides) -> Alert:
    values = dict(
        alert_id=42,
        created_at=datetime(2026, 8, 31, 10, tzinfo=timezone.utc),
        occurred_at=datetime(2026, 8, 31, 10, tzinfo=timezone.utc),
        source=AlertSource.RULE,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.NEW,
        alert_type="CONGESTION_RISK",
        title="queue",
        metadata_={},
        site_id=SITE_ID,
    )
    values.update(overrides)
    return Alert(**values)


def _ctx(site_id: int = SITE_ID) -> OperationalContext:
    site = Site(site_id=site_id, code=f"SITE-{site_id}", name="Site", active=True)
    return OperationalContext(
        site=site,
        shift=None,
        sim_now=datetime(2026, 8, 31, 12, tzinfo=timezone.utc),
        shift_window_start=datetime(2026, 8, 31, 6, tzinfo=timezone.utc),
        shift_window_end=datetime(2026, 8, 31, 14, tzinfo=timezone.utc),
    )


class FakeSession:
    def __init__(self, *, alert=None, extra=None):
        self.alert = alert
        self.extra = extra or {}
        self.added = []

    def get(self, model, pk):
        if model is Alert and self.alert is not None and self.alert.alert_id == pk:
            return self.alert
        item = self.extra.get((model, pk))
        if item is not None:
            return item
        for key, value in self.extra.items():
            if key[0] is model and getattr(value, "equipment_id", None) == pk:
                return value
            if key[0] is model and getattr(value, "zone_id", None) == pk:
                return value
        return None

    def scalars(self, _query):
        class Rows:
            def all(self):
                return []

        return Rows()

    def scalar(self, _query):
        return None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        return None

    def refresh(self, obj):
        return None


def _raises_404(fn):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == 404
    assert exc.value.detail == "Alert not found"


def test_site_scope_sql_includes_legacy_equipment_and_zone_disjuncts():
    sql = str(select(Alert).where(_site_scope(SITE_ID)).compile()).lower()
    assert "site_id" in sql
    assert "equipment" in sql
    assert "zones" in sql or "zone" in sql


def test_same_site_get_site_alert_succeeds():
    alert = _alert(site_id=SITE_ID)
    assert get_site_alert_or_404(FakeSession(alert=alert), SITE_ID, "alert-42") is alert


def test_cross_site_get_site_alert_is_404():
    alert = _alert(site_id=OTHER_SITE)
    _raises_404(lambda: get_site_alert_or_404(FakeSession(alert=alert), SITE_ID, "alert-42"))


def test_equipment_linked_legacy_alert_belonging_to_site_is_accepted():
    truck = Equipment(equipment_id=10, site_id=SITE_ID, code="TRK-010", type=EquipmentType.HAUL_TRUCK, active=True)
    alert = _alert(site_id=None, equipment_id=10)
    session = FakeSession(alert=alert, extra={(Equipment, 10): truck})
    assert get_site_alert_or_404(session, SITE_ID, "alert-42") is alert


def test_zone_linked_legacy_alert_belonging_to_site_is_accepted():
    zone = SimpleNamespace(zone_id=8, site_id=SITE_ID)
    alert = _alert(site_id=None, zone_id=8)
    session = FakeSession(alert=alert, extra={(Zone, 8): zone})
    assert get_site_alert_or_404(session, SITE_ID, "alert-42") is alert


def test_unrelated_site_alert_is_never_processed():
    truck = Equipment(equipment_id=10, site_id=OTHER_SITE, code="TRK-010", type=EquipmentType.HAUL_TRUCK, active=True)
    zone = SimpleNamespace(zone_id=8, site_id=OTHER_SITE)
    alert = _alert(site_id=OTHER_SITE, equipment_id=10, zone_id=8)
    session = FakeSession(alert=alert, extra={(Equipment, 10): truck, (Zone, 8): zone})
    _raises_404(lambda: get_site_alert_or_404(session, SITE_ID, "alert-42"))
    _raises_404(lambda: inbox_detail(session, _ctx(), "alert-42"))
    _raises_404(lambda: create_optimization_run(session, _ctx(), "alert-42"))
    assert session.added == []


def test_missing_alert_is_404():
    _raises_404(lambda: get_site_alert_or_404(FakeSession(alert=None), SITE_ID, "alert-42"))


def test_same_site_list_optimization_runs_succeeds():
    alert = _alert(site_id=SITE_ID)
    assert list_optimization_runs(FakeSession(alert=alert), _ctx(), "alert-42") == []


def test_same_site_actions_inbox_detail_succeeds():
    alert = _alert(site_id=SITE_ID)
    body = inbox_detail(FakeSession(alert=alert), _ctx(), "alert-42")
    assert body["alert"]["id"] == "alert-42"
    assert body["investigationId"] is None


def test_cross_site_actions_inbox_detail_returns_404():
    alert = _alert(site_id=OTHER_SITE)
    _raises_404(lambda: inbox_detail(FakeSession(alert=alert), _ctx(), "alert-42"))


def test_same_site_optimization_succeeds(monkeypatch):
    alert = _alert(site_id=SITE_ID, alert_type="EQUIPMENT_ANOMALY")
    session = FakeSession(alert=alert)
    llm_calls = []
    monkeypatch.setattr(
        "app.optimization.service.get_weather_context",
        lambda *_args, **_kwargs: SimpleNamespace(status=SimpleNamespace(value="UNAVAILABLE"), unavailableReason="test", current=None),
    )
    monkeypatch.setattr("app.ai.llm.provider.create_llm_provider", lambda *_a, **_k: llm_calls.append(1))
    payload = create_optimization_run(session, _ctx(), "alert-42")
    assert payload["alertId"] == "alert-42"
    assert payload["outcome"] == "NOT_APPLICABLE"
    assert session.added
    assert llm_calls == []


def test_cross_site_optimization_returns_404_and_does_not_persist(monkeypatch):
    alert = _alert(site_id=OTHER_SITE)
    session = FakeSession(alert=alert)
    calls = []

    def boom(*_args, **_kwargs):
        calls.append(1)
        raise AssertionError("persist_run must not run for a cross-site alert")

    monkeypatch.setattr("app.optimization.service.persist_run", boom)
    monkeypatch.setattr("app.optimization.service.get_weather_context", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("weather")))
    _raises_404(lambda: create_optimization_run(session, _ctx(), "alert-42"))
    assert calls == []
    assert session.added == []


def test_cross_site_list_optimization_runs_returns_404():
    alert = _alert(site_id=OTHER_SITE)
    _raises_404(lambda: list_optimization_runs(FakeSession(alert=alert), _ctx(), "alert-42"))


def test_optimization_and_inbox_do_not_import_llm():
    from pathlib import Path

    for rel in ("app/optimization/inbox.py", "app/optimization/service.py", "app/optimization/solver.py"):
        text = Path(rel).read_text(encoding="utf-8")
        assert "app.ai.llm" not in text
        assert "from app.ai.graph" not in text
        assert "create_llm_provider" not in text
