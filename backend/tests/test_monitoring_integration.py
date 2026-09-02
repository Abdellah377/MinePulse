from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.ai.contracts import (
    ConfidenceLevel,
    DiagnosisResult,
    InvestigationConclusion,
    InvestigationRecommendation,
    RecommendationAction,
)
from app.ai.service import run_investigation
from app.config import Settings
from app.db.database import SessionLocal
from app.db.enums import AlertSeverity, AlertSource, AlertStatus, EquipmentState, EquipmentType
from app.db.models import AiInvestigation, Alert, Equipment, Site
from app.db.models.telemetry import EquipmentState as EquipmentStateRow
from app.monitoring.detectors import detect_unexpected_stops
from app.monitoring.service import MonitoringService
from app.services.operational.alerts import list_site_alerts
from app.services.operational.context import get_operational_context

requires_integration = pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="persisted monitoring evaluation requires --integration and PostgreSQL",
)


class MonitoringMockProvider:
    provider_name = "mock"
    model_name = "monitoring-zero-cost"

    def diagnose(self, payload):
        return DiagnosisResult(
            hypotheses=[], requested_information=[], contradictions=[], can_conclude=False,
            confidence=ConfidenceLevel.LOW,
            confidence_rationale="The operational symptom is present but no cause is established.",
            reasoning_summary="A stopped state warrants investigation; available evidence remains inconclusive.",
        )

    def build_conclusion(self, payload):
        return InvestigationConclusion(
            summary="The equipment is stopped; available evidence does not establish why.",
            root_cause=None, reliable_root_cause=False,
            unresolved_uncertainties=["The cause of the stop is not confirmed."],
            confidence=ConfidenceLevel.LOW,
        )

    def build_recommendation(self, payload):
        return InvestigationRecommendation(
            action_type=RecommendationAction.VERIFY_OPERATIONAL_CONDITION,
            description="Verify the observed stopped condition.",
            rationale="Human validation is required before intervention.",
            human_validation_required=True,
        )

    def discuss_recommendation(self, payload):
        from app.ai.contracts import RecommendationDiscussionReply
        return RecommendationDiscussionReply(reply="Monitoring mock discussion.", cited_evidence_ids=[], operator_claims_unverified=[])


@requires_integration
def test_site_level_monitoring_alert_is_visible_without_fake_equipment_scope():
    with SessionLocal() as session:
        try:
            site = session.scalar(select(Site).where(Site.active.is_(True)).order_by(Site.site_id))
            if site is None:
                pytest.skip("No active persisted site")
        except Exception as exc:
            pytest.skip(f"PostgreSQL unavailable: {exc}")
        operational_now = get_operational_context(session, site_code=site.code).sim_now
        alert = Alert(
            site_id=site.site_id,
            created_at=datetime.now(timezone.utc),
            occurred_at=operational_now,
            source=AlertSource.RULE,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.NEW,
            alert_type="PRODUCTION_DEVIATION",
            title="Site-level monitoring test",
            equipment_id=None,
            zone_id=None,
            metadata_={"monitoring": {"deduplicationKey": f"test:{uuid4()}"}},
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        try:
            assert alert in list_site_alerts(session, site.site_id, active_only=True)
            assert alert.equipment_id is None and alert.zone_id is None
        finally:
            session.delete(alert)
            session.commit()


@requires_integration
def test_persisted_stop_creates_one_automatic_investigation_then_deduplicates():
    """Persisted state -> operational services -> detector -> public AI service boundary."""
    with SessionLocal() as session:
        try:
            site = session.scalar(select(Site).where(Site.active.is_(True)).order_by(Site.site_id))
            if site is None:
                pytest.skip("No active persisted site")
            context = get_operational_context(session, site_code=site.code)
        except Exception as exc:
            pytest.skip(f"PostgreSQL/operational context unavailable: {exc}")

        code = f"MON-{uuid4().hex[:10]}"
        equipment = Equipment(
            site_id=site.site_id, code=code, type=EquipmentType.HAUL_TRUCK,
            current_state=EquipmentState.STOPPED_UNDEFINED, active=True,
        )
        session.add(equipment)
        session.commit()
        session.refresh(equipment)
        state = EquipmentStateRow(
            equipment_id=equipment.equipment_id,
            state=EquipmentState.STOPPED_UNDEFINED,
            start_time=context.sim_now - timedelta(minutes=5),
            end_time=None,
            reason_code=None,
            reason_text=None,
            reason_source=None,
            reason_confirmed=False,
            metadata_={},
        )
        session.add(state)
        session.commit()

        settings = Settings(
            _env_file=None,
            monitoring_enabled=True,
            monitoring_auto_investigate=True,
            monitoring_unexpected_stop_minutes=4,
            monitoring_investigation_cooldown_minutes=15,
        )
        provider = MonitoringMockProvider()
        service = MonitoringService(
            settings=settings,
            detectors=(detect_unexpected_stops,),
            investigation_runner=lambda db, trigger: run_investigation(
                db, trigger, provider=provider, max_iterations=1
            ),
        )
        try:
            first = service.run_cycle(session)
            second = service.run_cycle(session)
            investigations = list(session.scalars(select(AiInvestigation).where(
                AiInvestigation.equipment_id == equipment.equipment_id,
                AiInvestigation.trigger_source == "AUTOMATIC_MONITORING",
            )).all())
            alerts = list(session.scalars(select(Alert).where(Alert.equipment_id == equipment.equipment_id)).all())

            assert first["investigations"] == 1
            assert second["investigations"] == 0
            assert second["deduplicated"] == 1
            assert len(investigations) == 1
            assert len(alerts) == 1
            assert alerts[0].occurred_at == context.sim_now
            assert alerts[0].created_at != alerts[0].occurred_at
            assert investigations[0].trigger_data["source_record_id"] == f"alert-{alerts[0].alert_id}"
            assert investigations[0].trigger_data["trigger_source"] == "AUTOMATIC_MONITORING"
        finally:
            session.execute(delete(AiInvestigation).where(AiInvestigation.equipment_id == equipment.equipment_id))
            session.execute(delete(Alert).where(Alert.equipment_id == equipment.equipment_id))
            session.execute(delete(EquipmentStateRow).where(EquipmentStateRow.equipment_id == equipment.equipment_id))
            session.delete(equipment)
            session.commit()
