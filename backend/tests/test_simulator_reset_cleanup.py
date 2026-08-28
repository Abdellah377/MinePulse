from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, or_, select

from app.ai.contracts import TriggerSource
from app.db.database import SessionLocal
from app.db.enums import AlertSeverity, AlertSource, AlertStatus, RecommendationStatus
from app.db.models import AiInvestigation, AiRecommendation, Alert, Site
from app.services.operational.alerts import list_site_alerts
from simulator.reset_cleanup import clear_simulation_run_data

requires_integration = pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="reset lifecycle verification requires --integration and PostgreSQL",
)

NOW = datetime(2026, 1, 29, 17, 50, tzinfo=timezone.utc)


def _site(code: str) -> Site:
    return Site(
        code=code,
        name=code,
        timezone="UTC",
        active=True,
        created_at=datetime.now(timezone.utc),
    )


def _remove_failed_test_sites(session) -> None:
    session.execute(delete(Site).where(or_(
        Site.code.like("RESET-SIM-%"),
        Site.code.like("RESET-REAL-%"),
        Site.code.like("ORDER-%"),
    )))
    session.commit()


def _alert(site_id: int, *, source: AlertSource, title: str, monitoring: bool = False, ts=NOW) -> Alert:
    return Alert(
        site_id=site_id,
        created_at=datetime.now(timezone.utc),
        occurred_at=ts,
        source=source,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.NEW,
        alert_type="RESET_TEST",
        title=title,
        metadata_={"monitoring": {"deduplicationKey": title}} if monitoring else {},
    )


def _investigation(site_id: int, source_record_id: str, *, source: TriggerSource) -> AiInvestigation:
    investigation_id = uuid4()
    now = datetime.now(timezone.utc)
    return AiInvestigation(
        investigation_id=investigation_id,
        created_at=now,
        updated_at=now,
        completed_at=now,
        status="COMPLETED_WITH_UNCERTAINTY",
        trigger_type="OPERATIONAL_EVENT",
        trigger_source=source.value,
        site_id=site_id,
        shift_id=None,
        equipment_id=None,
        zone_id=None,
        iteration_count=1,
        max_iterations=3,
        graph_version="reset-test",
        provider="mock",
        model="mock",
        trigger_data={
            "trigger_type": "OPERATIONAL_EVENT",
            "trigger_source": source.value,
            "site_id": site_id,
            "source_record_id": source_record_id,
            "payload": {},
        },
        operational_context=None,
        evidence=[],
        hypotheses=[],
        requested_information=[],
        contradictions=[],
        conclusion=None,
        recommendation=None,
        error=None,
        metadata_={},
        debug_trace={"events": [{"event_type": "INVESTIGATION_COMPLETED"}], "stop_reason": "PROBABLE_CAUSE"},
    )


@requires_integration
def test_reset_clears_only_simulation_alerts_and_linked_ai_records():
    suffix = uuid4().hex[:10]
    simulation_site = _site(f"RESET-SIM-{suffix}")
    real_site = _site(f"RESET-REAL-{suffix}")
    with SessionLocal() as session:
        _remove_failed_test_sites(session)
        session.add_all([simulation_site, real_site])
        session.commit()
        session.refresh(simulation_site)
        session.refresh(real_site)

        fms = _alert(simulation_site.site_id, source=AlertSource.FMS, title="old-fms")
        monitored = _alert(
            simulation_site.site_id, source=AlertSource.RULE,
            title="old-monitoring", monitoring=True,
        )
        sim_rule = _alert(simulation_site.site_id, source=AlertSource.RULE, title="preserved-human-rule")
        real_rule = _alert(
            real_site.site_id, source=AlertSource.RULE,
            title="preserved-real-monitoring", monitoring=True,
        )
        for row in (fms, monitored, sim_rule, real_rule):
            session.add(row)
            session.commit()
            session.refresh(row)

        automatic = _investigation(
            simulation_site.site_id, f"alert-{monitored.alert_id}",
            source=TriggerSource.AUTOMATIC_MONITORING,
        )
        manual_linked = _investigation(
            simulation_site.site_id, f"alert-{fms.alert_id}",
            source=TriggerSource.USER_INVESTIGATE,
        )
        manual_unrelated = _investigation(
            simulation_site.site_id, "human-reference-record",
            source=TriggerSource.USER_INVESTIGATE,
        )
        recommendation = AiRecommendation(
            created_at=datetime.now(timezone.utc),
            trigger_type="ALERT",
            trigger_id=fms.alert_id,
            problem_summary="Temporary linked simulation recommendation",
            action_type="VERIFY_OPERATIONAL_CONDITION",
            action_description="Verify",
            status=RecommendationStatus.GENERATED,
            assumptions=[], evidence=[], constraints=[], metadata_={},
        )
        session.add_all([automatic, manual_linked, manual_unrelated, recommendation])
        session.commit()
        ids = {
            "automatic": automatic.investigation_id,
            "manual_linked": manual_linked.investigation_id,
            "manual_unrelated": manual_unrelated.investigation_id,
            "recommendation": recommendation.recommendation_id,
        }

        try:
            counts = clear_simulation_run_data(session, site_code=simulation_site.code)
            session.commit()  # Also proves deletion order satisfies foreign keys.
            session.expire_all()

            assert session.get(Alert, fms.alert_id) is None
            assert session.get(Alert, monitored.alert_id) is None
            assert session.get(Alert, sim_rule.alert_id) is not None
            assert session.get(Alert, real_rule.alert_id) is not None
            assert session.get(AiInvestigation, ids["automatic"]) is None
            assert session.get(AiInvestigation, ids["manual_linked"]) is None
            assert session.get(AiInvestigation, ids["manual_unrelated"]) is not None
            assert session.get(AiRecommendation, ids["recommendation"]) is None
            assert counts["alerts"] == 2
            assert counts["ai_investigations"] == 2

            # A fresh run cannot mix the prior run's alert IDs/timestamps.
            fresh = _alert(
                simulation_site.site_id,
                source=AlertSource.FMS,
                title="fresh-run",
                ts=datetime(2026, 1, 29, 7, 13, tzinfo=timezone.utc),
            )
            session.add(fresh)
            session.commit()
            visible = list_site_alerts(session, simulation_site.site_id)
            assert [row.title for row in visible] == ["preserved-human-rule", "fresh-run"]
            assert all(row.title not in {"old-fms", "old-monitoring"} for row in visible)
        finally:
            session.delete(simulation_site)
            session.delete(real_site)
            session.commit()


@requires_integration
def test_backend_alert_order_uses_full_timestamp_newest_first():
    site = _site(f"ORDER-{uuid4().hex[:10]}")
    with SessionLocal() as session:
        _remove_failed_test_sites(session)
        session.add(site)
        session.commit()
        session.refresh(site)
        old_hour = _alert(
            site.site_id, source=AlertSource.RULE, title="17:50 old run",
            ts=datetime(2026, 1, 29, 17, 50, tzinfo=timezone.utc),
        )
        next_day = _alert(
            site.site_id, source=AlertSource.RULE, title="07:13 new run",
            ts=datetime(2026, 1, 30, 7, 13, tzinfo=timezone.utc),
        )
        session.add(old_hour)
        session.commit()
        session.add(next_day)
        session.commit()
        try:
            rows = list_site_alerts(session, site.site_id)
            assert [row.title for row in rows] == ["07:13 new run", "17:50 old run"]
        finally:
            session.delete(site)
            session.commit()
