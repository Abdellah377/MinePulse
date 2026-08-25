from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.ai.contracts import (
    EvidenceItem,
    EvidenceKind,
    InvestigationSubject,
    InvestigationTrigger,
    TriggerType,
)


def test_trigger_contract_supports_production_and_future_sources():
    trigger = InvestigationTrigger(
        trigger_type=TriggerType.USER_INVESTIGATE,
        subject=InvestigationSubject.PRODUCTION,
        source="performance-page",
        site_id=7,
        shift_id=9,
        occurred_at=datetime(2026, 8, 24, 9, 0),
        payload={"reason": "production below target"},
    )

    assert trigger.occurred_at.tzinfo == timezone.utc
    assert trigger.model_dump(mode="json")["subject"] == "PRODUCTION"


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
