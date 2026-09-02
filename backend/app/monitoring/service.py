"""Monitoring cycle orchestration and alert/investigation deduplication."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import InvestigationResult, InvestigationTrigger, TriggerSource
from app.ai.service import run_investigation
from app.config import Settings, get_settings
from app.db.database import SessionLocal
from app.db.enums import AlertSeverity, AlertSource, AlertStatus
from app.db.models import AiInvestigation, Alert, Site
from app.monitoring.contracts import MonitoringCandidate, MonitoringSnapshot
from app.monitoring.coordination import monitoring_reset_coordinator
from app.monitoring.detectors import DEFAULT_DETECTORS, Detector
from app.monitoring.predictive import attach_failure_risk_predictions
from app.services.operational.alerts import list_site_alerts
from app.services.operational.context import get_operational_context
from app.services.operational.equipment import build_fleet_bulk_context, list_site_equipment
from app.services.operational.production import production_summary

logger = logging.getLogger(__name__)

InvestigationRunner = Callable[[Session, InvestigationTrigger], InvestigationResult]

_SEVERITY_RANK = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
_AI_TO_ALERT_SEVERITY = {
    "INFO": AlertSeverity.INFO,
    "WARNING": AlertSeverity.WARNING,
    "CRITICAL": AlertSeverity.CRITICAL,
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def build_monitoring_snapshot(session: Session, site: Site) -> MonitoringSnapshot:
    """Resolve one consistent operational snapshot through existing services."""
    context = get_operational_context(session, site_code=site.code)
    equipment = list_site_equipment(session, context, active_only=True)
    return MonitoringSnapshot(
        context=context,
        equipment=equipment,
        fleet=build_fleet_bulk_context(session, equipment, context),
        production=production_summary(session, context),
        active_alerts=list_site_alerts(session, site.site_id, limit=500, active_only=True),
    )


def _default_investigation_runner(session: Session, trigger: InvestigationTrigger) -> InvestigationResult:
    return run_investigation(session, trigger)


def _coalesce_existing_alert_findings(candidates: list[MonitoringCandidate]) -> list[MonitoringCandidate]:
    """Prefer a linked authoritative alert over a derived finding for the same symptom scope."""
    def scope(item: MonitoringCandidate) -> tuple:
        if item.equipment_id is not None:
            return item.trigger_type, item.site_id, "equipment", item.equipment_id
        if item.zone_id is not None:
            return item.trigger_type, item.site_id, "zone", item.zone_id
        return item.trigger_type, item.site_id, "site", item.site_id

    linked_scopes = {
        scope(item)
        for item in candidates
        if item.source_alert_id is not None
    }
    return [
        item for item in candidates
        if item.source_alert_id is not None
        or scope(item) not in linked_scopes
    ]


class MonitoringService:
    """Run detectors and persist operational alerts. LangGraph is opt-in only."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        detectors: Iterable[Detector] = DEFAULT_DETECTORS,
        investigation_runner: InvestigationRunner = _default_investigation_runner,
        snapshot_builder: Callable[[Session, Site], MonitoringSnapshot] = build_monitoring_snapshot,
    ) -> None:
        self.settings = settings or get_settings()
        self.detectors = tuple(detectors)
        self.investigation_runner = investigation_runner
        self.snapshot_builder = snapshot_builder

    def run_cycle(self, session: Session) -> dict[str, int]:
        counts = {"sites": 0, "candidates": 0, "investigations": 0, "deduplicated": 0, "errors": 0}
        if not self.settings.monitoring_enabled:
            logger.debug("Operational monitoring is disabled")
            return counts

        generation = monitoring_reset_coordinator.cycle_token()
        if generation is None:
            logger.info("Monitoring cycle skipped during operational reset")
            return counts

        logger.info("Monitoring cycle started")
        sites = list(session.scalars(select(Site).where(Site.active.is_(True)).order_by(Site.site_id)).all())
        for site in sites:
            try:
                snapshot = self.snapshot_builder(session, site)
                counts["sites"] += 1
            except Exception:
                counts["errors"] += 1
                logger.exception("Monitoring snapshot failed", extra={"site_id": site.site_id})
                session.rollback()
                continue

            try:
                snapshot = attach_failure_risk_predictions(session, snapshot)
            except Exception:
                logger.exception(
                    "Failure-Risk scoring failed; predictive detector will emit nothing",
                    extra={"site_id": site.site_id},
                )

            candidates: list[MonitoringCandidate] = []
            for detector in self.detectors:
                try:
                    findings = detector(snapshot, self.settings)
                    candidates.extend(findings)
                    for candidate in findings:
                        logger.info(
                            "Monitoring detector fired",
                            extra={
                                "detector_id": candidate.detector_id,
                                "site_id": candidate.site_id,
                                "equipment_id": candidate.equipment_id,
                                "severity": candidate.severity.value,
                            },
                        )
                except Exception:
                    counts["errors"] += 1
                    logger.exception(
                        "Monitoring detector failed",
                        extra={"detector": getattr(detector, "__name__", type(detector).__name__), "site_id": site.site_id},
                    )
            candidates = _coalesce_existing_alert_findings(candidates)
            counts["candidates"] += len(candidates)
            for candidate in candidates:
                try:
                    if self._process_candidate(session, candidate, generation=generation):
                        counts["investigations"] += 1
                    else:
                        counts["deduplicated"] += 1
                except Exception:
                    counts["errors"] += 1
                    logger.exception(
                        "Monitoring candidate processing failed",
                        extra={"detector_id": candidate.detector_id, "deduplication_key": candidate.deduplication_key},
                    )
                    session.rollback()
        logger.info("Monitoring cycle completed", extra=counts)
        return counts

    def _matching_alert(self, session: Session, candidate: MonitoringCandidate) -> Alert | None:
        if candidate.source_alert_id is not None:
            alert = session.get(Alert, candidate.source_alert_id)
            if alert is not None and alert.status != AlertStatus.RESOLVED:
                return alert
        active = list_site_alerts(session, candidate.site_id, limit=500, active_only=True)
        for alert in active:
            monitoring = (alert.metadata_ or {}).get("monitoring") or {}
            if monitoring.get("deduplicationKey") == candidate.deduplication_key:
                return alert
        return None

    def _recent_investigation_exists(self, session: Session, candidate: MonitoringCandidate, alert: Alert) -> bool:
        # Durable investigation creation timestamps use wall-clock UTC, while
        # detector timestamps may use an accelerated operational clock.
        cooldown_start = datetime.now(timezone.utc) - timedelta(minutes=self.settings.monitoring_investigation_cooldown_minutes)
        source_record_id = f"alert-{alert.alert_id}"
        return session.scalar(
            select(AiInvestigation.investigation_id).where(
                AiInvestigation.site_id == candidate.site_id,
                AiInvestigation.created_at >= cooldown_start,
                AiInvestigation.trigger_data["source_record_id"].as_string() == source_record_id,
            ).limit(1)
        ) is not None

    def _should_deduplicate(self, session: Session, candidate: MonitoringCandidate, alert: Alert) -> bool:
        monitoring = (alert.metadata_ or {}).get("monitoring") or {}
        previous_severity = monitoring.get("lastInvestigatedSeverity")
        escalated = previous_severity is not None and (
            _SEVERITY_RANK[candidate.severity.value] > _SEVERITY_RANK.get(str(previous_severity), 0)
        )
        if escalated:
            return False
        raw_last = monitoring.get("lastInvestigationStartedAt")
        if raw_last:
            try:
                last = datetime.fromisoformat(str(raw_last).replace("Z", "+00:00"))
                return _utc(candidate.detected_at) - _utc(last) < timedelta(
                    minutes=self.settings.monitoring_investigation_cooldown_minutes
                )
            except (TypeError, ValueError):
                logger.warning("Invalid monitoring cooldown timestamp", extra={"alert_id": alert.alert_id})
        return self._recent_investigation_exists(session, candidate, alert)

    def _create_alert(self, session: Session, candidate: MonitoringCandidate) -> Alert:
        monitoring: dict[str, object] = {
            "detectorId": candidate.detector_id,
            "deduplicationKey": candidate.deduplication_key,
            "metric": candidate.metric,
            "value": candidate.value,
            "threshold": candidate.threshold,
            "unit": candidate.unit,
        }
        if candidate.alert_source == AlertSource.PREDICTION:
            context = candidate.context or {}
            monitoring.update({
                "probability": candidate.value,
                "horizonMinutes": context.get("horizonMinutes", 60),
                "modelVersion": context.get("modelVersion"),
                "modelType": context.get("modelType"),
                "servedPredictor": context.get("servedPredictor"),
                "dataClass": context.get("dataClass"),
                "topSignals": context.get("topSignals"),
                "source": context.get("source", "FAILURE_RISK_V1"),
                "riskLevel": context.get("riskLevel"),
            })
        alert = Alert(
            site_id=candidate.site_id,
            created_at=datetime.now(timezone.utc),
            occurred_at=candidate.detected_at,
            predicted_for=candidate.predicted_for,
            source=candidate.alert_source,
            severity=_AI_TO_ALERT_SEVERITY[candidate.severity.value],
            status=AlertStatus.NEW,
            alert_type=candidate.trigger_type.value,
            title=candidate.title,
            description=candidate.reason,
            equipment_id=candidate.equipment_id,
            zone_id=candidate.zone_id,
            confidence=None,
            estimated_impact_t=None,
            estimated_impact_tph=None,
            metadata_={"monitoring": monitoring},
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return alert

    def _update_alert(
        self,
        session: Session,
        alert: Alert,
        candidate: MonitoringCandidate,
        *,
        investigated: bool,
    ) -> None:
        metadata = dict(alert.metadata_ or {})
        monitoring = dict(metadata.get("monitoring") or {})
        monitoring.update({
            "detectorId": candidate.detector_id,
            "deduplicationKey": candidate.deduplication_key,
            "metric": candidate.metric,
            "value": candidate.value,
            "threshold": candidate.threshold,
            "unit": candidate.unit,
        })
        if investigated:
            monitoring.update({
                "lastInvestigationStartedAt": candidate.detected_at.isoformat(),
                "lastInvestigatedSeverity": candidate.severity.value,
            })
        metadata["monitoring"] = monitoring
        alert.metadata_ = metadata
        desired = _AI_TO_ALERT_SEVERITY[candidate.severity.value]
        if _SEVERITY_RANK[desired.value] > _SEVERITY_RANK[alert.severity.value]:
            alert.severity = desired
        session.commit()

    def _mark_result(self, session: Session, alert_id: int, result: InvestigationResult) -> None:
        alert = session.get(Alert, alert_id)
        if alert is None:
            return
        metadata = dict(alert.metadata_ or {})
        monitoring = dict(metadata.get("monitoring") or {})
        monitoring.update({
            "lastInvestigationId": str(result.investigation_id),
            "lastInvestigationStatus": result.status.value,
            "lastInvestigationCompletedAt": result.completed_at.isoformat() if result.completed_at else None,
        })
        metadata["monitoring"] = monitoring
        alert.metadata_ = metadata
        session.commit()

    def _process_candidate(
        self,
        session: Session,
        candidate: MonitoringCandidate,
        *,
        generation: int | None = None,
    ) -> bool:
        token = monitoring_reset_coordinator.cycle_token() if generation is None else generation
        if token is None:
            return False
        with monitoring_reset_coordinator.candidate_guard(token) as current:
            if not current:
                logger.info("Stale monitoring candidate discarded after reset")
                return False
            alert = self._matching_alert(session, candidate) or self._create_alert(session, candidate)
            if not self.settings.monitoring_auto_investigate:
                self._update_alert(session, alert, candidate, investigated=False)
                logger.info(
                    "Monitoring alert persisted without automatic investigation",
                    extra={
                        "alert_id": alert.alert_id,
                        "detector_id": candidate.detector_id,
                        "deduplication_key": candidate.deduplication_key,
                    },
                )
                return False
            if self._should_deduplicate(session, candidate, alert):
                logger.info(
                    "Monitoring candidate deduplicated",
                    extra={"alert_id": alert.alert_id, "deduplication_key": candidate.deduplication_key},
                )
                return False
            self._update_alert(session, alert, candidate, investigated=True)
        trigger = InvestigationTrigger(
            trigger_type=candidate.trigger_type,
            trigger_source=TriggerSource.AUTOMATIC_MONITORING,
            source=f"monitoring:{candidate.detector_id}",
            site_id=candidate.site_id,
            shift_id=candidate.shift_id,
            equipment_id=candidate.equipment_id,
            zone_id=candidate.zone_id,
            occurred_at=candidate.detected_at,
            severity=candidate.severity,
            source_record_id=f"alert-{alert.alert_id}",
            payload={
                "detector_id": candidate.detector_id,
                "reason": candidate.reason,
                "metric": candidate.metric,
                "value": candidate.value,
                "threshold": candidate.threshold,
                "unit": candidate.unit,
                "context": candidate.context,
            },
        )
        try:
            result = self.investigation_runner(session, trigger)
        except Exception as exc:
            session.rollback()
            alert = session.get(Alert, alert.alert_id)
            if alert is not None:
                metadata = dict(alert.metadata_ or {})
                monitoring = dict(metadata.get("monitoring") or {})
                monitoring["lastInvestigationErrorType"] = type(exc).__name__
                metadata["monitoring"] = monitoring
                alert.metadata_ = metadata
                session.commit()
            logger.exception(
                "Automatic investigation failed",
                extra={"alert_id": alert.alert_id if alert else None, "detector_id": candidate.detector_id},
            )
            raise
        with monitoring_reset_coordinator.candidate_guard(token) as current:
            if not current:
                row = session.get(AiInvestigation, result.investigation_id)
                if row is not None:
                    session.delete(row)
                    session.commit()
                logger.info(
                    "Late automatic investigation discarded after reset",
                    extra={"investigation_id": str(result.investigation_id)},
                )
                return False
            self._mark_result(session, alert.alert_id, result)
        logger.info(
            "Automatic investigation created",
            extra={"investigation_id": str(result.investigation_id), "alert_id": alert.alert_id},
        )
        return True


def run_monitoring_cycle() -> dict[str, int]:
    """Open an isolated DB session for one scheduler/manual monitoring cycle."""
    with SessionLocal() as session:
        return MonitoringService().run_cycle(session)
