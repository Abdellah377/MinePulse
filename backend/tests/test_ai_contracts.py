from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.ai.contracts import (
    EvidenceItem,
    EvidenceKind,
    DiagnosisStatus,
    InvestigationConclusion,
    InvestigationSubject,
    InvestigationTrigger,
    TriggerSource,
    TriggerType,
    ConfidenceLevel,
)


def test_trigger_contract_supports_production_and_future_sources():
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.PRODUCTION_DEVIATION,
        trigger_source=TriggerSource.USER_INVESTIGATE,
        subject=InvestigationSubject.PRODUCTION,
        source="performance-page",
        site_id=7,
        shift_id=9,
        occurred_at=datetime(2026, 8, 24, 9, 0),
        payload={"reason": "production below target"},
    )

    assert trigger.occurred_at.tzinfo == timezone.utc
    payload = trigger.model_dump(mode="json")
    assert payload["trigger_type"] == "PRODUCTION_DEVIATION"
    assert payload["trigger_source"] == "USER_INVESTIGATE"
    assert payload["subject"] == "PRODUCTION"


def test_legacy_trigger_is_normalized_without_losing_source_detail():
    trigger = InvestigationTrigger(
        trigger_type="EXISTING_ALERT",
        subject=InvestigationSubject.EQUIPMENT,
        source="alerts-page",
        source_record_id="alert-42",
        site_id=7,
        payload={"legacy": True},
    )

    assert trigger.trigger_type == TriggerType.EQUIPMENT_ANOMALY
    assert trigger.trigger_source == TriggerSource.EXISTING_ALERT
    assert trigger.source == "alerts-page"
    assert trigger.source_record_id == "alert-42"
    assert trigger.payload == {"legacy": True}


def test_evidence_provenance_serializes_zero_as_observed_value():
    item = EvidenceItem(
        evidence_id="ev-zero",
        kind=EvidenceKind.DERIVED_METRIC,
        source_tool="cycle_performance",
        source_service="app.services.operational.cycles.shift_trip_counts",
        metric="completed_cycles",
        value=0,
        available=True,
        site_id=1,
        shift_id=2,
        observed_at=datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc),
        source_record_ids=["shift:2"],
    )

    payload = item.model_dump(mode="json")
    assert payload["value"] == 0
    assert payload["available"] is True
    assert payload["source_service"].endswith("shift_trip_counts")


def test_unavailable_evidence_requires_null_not_synthetic_zero():
    with pytest.raises(ValidationError, match="unavailable evidence must have a null value"):
        EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool="missing",
            source_service="approved.service",
            metric="unknown_metric",
            value=0,
            available=False,
        )

    item = EvidenceItem(
        kind=EvidenceKind.FACT,
        source_tool="missing",
        source_service="approved.service",
        metric="unknown_metric",
        value=None,
        available=False,
    )
    assert item.model_dump(mode="json")["value"] is None


def test_investigation_conclusion_includes_three_state_diagnosis_status():
    probable = InvestigationConclusion(
        summary="Best-supported lubrication-related degradation.",
        diagnosis_status=DiagnosisStatus.PROBABLE,
        observed_condition="The truck stopped mechanically.",
        root_cause="Mechanical degradation consistent with a lubrication-related issue.",
        reliable_root_cause=False,
        causal_depth=2,
        contributing_factors=[
            {"statement": "Engine temperature increased before the stop.", "evidence_ids": ["ev-1"]}
        ],
        confidence=ConfidenceLevel.MEDIUM,
        unresolved_uncertainties=["Exact failed component is not confirmed."],
    )
    payload = probable.model_dump(mode="json")
    assert payload["diagnosis_status"] == "PROBABLE"
    assert payload["reliable_root_cause"] is False
    assert payload["causal_depth"] == 2
    assert payload["contributing_factors"][0]["evidence_ids"] == ["ev-1"]
    restored = InvestigationConclusion.model_validate(payload)
    assert restored.diagnosis_status is DiagnosisStatus.PROBABLE
    assert restored.reliable_root_cause is False

    default = InvestigationConclusion(summary="Unknown.", confidence=ConfidenceLevel.LOW)
    assert default.diagnosis_status is DiagnosisStatus.INCONCLUSIVE
    assert {item.value for item in DiagnosisStatus} == {"CONFIRMED", "PROBABLE", "INCONCLUSIVE"}


def test_predicted_mechanical_failure_risk_maps_to_maintenance_subject():
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.PREDICTED_MECHANICAL_FAILURE_RISK,
        trigger_source=TriggerSource.AUTOMATIC_MONITORING,
        site_id=7,
        occurred_at=datetime(2026, 8, 24, 9, 0),
    )
    assert trigger.subject == InvestigationSubject.MAINTENANCE
    assert trigger.trigger_type == TriggerType.PREDICTED_MECHANICAL_FAILURE_RISK
