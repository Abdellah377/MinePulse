"""End-to-end operational workflow hardening: resolve, inbox, optimize, decide."""

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from app.ai.contracts import RecommendationDecisionRequest, RecommendationDecisionType, RejectionReasonCategory
from app.ai.feedback import upsert_alert_decision
from app.db.enums import AlertSeverity, AlertSource, AlertStatus
from app.db.models import Alert, AiOptimizationRun, Site
from app.optimization.inbox import list_inbox
from app.optimization.persistence import persist_run
from app.optimization.service import create_optimization_run
from app.optimization.solver import OPTIMIZER_VERSION
from app.services.operational.alerts import get_site_alert_or_404, update_alert
from app.services.operational.context import OperationalContext


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


class WorkflowSession:
    def __init__(self, alert: Alert):
        self.alert = alert
        self.added = []
        self.deleted = []

    def get(self, model, pk):
        if model is Alert and self.alert is not None and self.alert.alert_id == pk:
            return self.alert
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

    def delete(self, row):
        self.deleted.append(row)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def test_explicit_resolve_keeps_row_and_sets_resolved_at():
    alert = _alert()
    session = WorkflowSession(alert)
    out = update_alert(session, "alert-42", site_id=SITE_ID, status="resolved", actor_label="Chef")
    assert out.status == AlertStatus.RESOLVED
    assert out.resolved_at is not None
    assert session.get(Alert, 42) is alert
    assert session.deleted == []


def test_cross_site_resolve_is_404_and_does_not_mutate():
    alert = _alert(site_id=OTHER_SITE)
    session = WorkflowSession(alert)
    try:
        update_alert(session, "alert-42", site_id=SITE_ID, status="resolved")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected 404")
    assert alert.status == AlertStatus.NEW
    assert alert.resolved_at is None


def test_actions_inbox_requests_active_only(monkeypatch):
    captured = {}

    def fake_page(_session, site_id, *, limit, cursor=None, active_only=False):
        captured["site_id"] = site_id
        captured["active_only"] = active_only
        captured["limit"] = limit
        captured["cursor"] = cursor
        return {"items": [], "nextCursor": "c2", "hasMore": True, "activeCount": 9}

    monkeypatch.setattr("app.optimization.inbox.page_site_alerts", fake_page)
    page = list_inbox(WorkflowSession(_alert()), _ctx(), cursor="c1", limit=20)
    assert captured == {"site_id": SITE_ID, "active_only": True, "limit": 20, "cursor": "c1"}
    assert page["hasMore"] is True
    assert page["nextCursor"] == "c2"
    assert page["activeCount"] == 9


def test_accept_reject_modify_do_not_resolve_alert():
    alert = _alert()
    session = WorkflowSession(alert)
    for decision in (
        RecommendationDecisionType.ACCEPTED,
        RecommendationDecisionType.REJECTED,
        RecommendationDecisionType.MODIFIED,
    ):
        upsert_alert_decision(
            session,
            42,
            RecommendationDecisionRequest(
                decision_type=decision,
                reason_category=RejectionReasonCategory.CONTRAINTE_NON_CONNUE_PAR_IA
                if decision != RecommendationDecisionType.ACCEPTED
                else None,
                reason_text="note" if decision != RecommendationDecisionType.ACCEPTED else None,
                alternative_action="alt" if decision == RecommendationDecisionType.MODIFIED else None,
            ),
            site_id=SITE_ID,
            original_recommendation={"alertId": "alert-42"},
        )
        assert alert.status == AlertStatus.NEW
        assert alert.resolved_at is None
    assert session.added


def test_repeated_optimization_creates_new_historical_run():
    session = WorkflowSession(_alert())
    first = persist_run(
        session,
        alert_id=42,
        site_id=SITE_ID,
        optimizer_version=OPTIMIZER_VERSION,
        weights={"w_travel": 1.0, "w_wait": 1.0},
        eligibility="OPTIMIZABLE",
        outcome="FEASIBLE",
        snapshot_digest="a",
        candidates=[{"candidateId": "c-1"}],
        recommended_candidate_id="c-1",
        weather_status="UNAVAILABLE",
        snapshot={"siteId": SITE_ID},
    )
    second = persist_run(
        session,
        alert_id=42,
        site_id=SITE_ID,
        optimizer_version=OPTIMIZER_VERSION,
        weights={"w_travel": 1.0, "w_wait": 1.0},
        eligibility="OPTIMIZABLE",
        outcome="NO_FEASIBLE_PLAN",
        snapshot_digest="b",
        candidates=[],
        recommended_candidate_id=None,
        weather_status="UNAVAILABLE",
        snapshot={"siteId": SITE_ID},
    )
    runs = [row for row in session.added if isinstance(row, AiOptimizationRun)]
    assert len(runs) == 2
    assert first.run_id != second.run_id
    assert first.outcome == "FEASIBLE"
    assert second.outcome == "NO_FEASIBLE_PLAN"


def test_same_site_optimization_persists_without_llm(monkeypatch):
    alert = _alert(alert_type="EQUIPMENT_ANOMALY")
    session = WorkflowSession(alert)
    llm_calls = []
    monkeypatch.setattr(
        "app.optimization.service.get_weather_context",
        lambda *_a, **_k: SimpleNamespace(status=SimpleNamespace(value="UNAVAILABLE"), unavailableReason="test", current=None),
    )
    monkeypatch.setattr("app.ai.llm.provider.create_llm_provider", lambda *_a, **_k: llm_calls.append(1))
    payload = create_optimization_run(session, _ctx(), "alert-42")
    assert payload["alertId"] == "alert-42"
    assert any(isinstance(row, AiOptimizationRun) for row in session.added)
    assert llm_calls == []


def test_get_site_alert_still_returns_resolved_row_for_history():
    alert = _alert(status=AlertStatus.RESOLVED)
    assert get_site_alert_or_404(WorkflowSession(alert), SITE_ID, "alert-42") is alert
