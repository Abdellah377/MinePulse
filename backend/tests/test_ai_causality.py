from datetime import datetime, timedelta, timezone

import pytest

from app.ai.causality import is_symptom_restatement
from app.ai.contracts import (
    ConfidenceLevel,
    DiagnosisResult,
    DiagnosisStatus,
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    InvestigationConclusion,
    InvestigationTrigger,
    TriggerSource,
    TriggerType,
)
from app.ai.graph import initial_state
from app.ai.nodes import InvestigationNodes

INCIDENT = datetime(2026, 8, 24, 10, tzinfo=timezone.utc)


def _trigger(trigger_type: TriggerType, reason: str) -> InvestigationTrigger:
    return InvestigationTrigger(
        trigger_type=trigger_type,
        trigger_source=TriggerSource.AUTOMATIC_MONITORING,
        site_id=1,
        shift_id=2,
        equipment_id=4,
        occurred_at=INCIDENT,
        payload={"reason": reason},
    )


def _evidence(*, observed_at: datetime | None = None) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev-causal",
        kind=EvidenceKind.DERIVED_METRIC,
        source_tool="loading_context",
        source_service="app.services.operational.loading.loading_service_context",
        metric="loading_queue_and_service_context",
        value={
            "windowStart": "2026-08-24T09:30:00+00:00",
            "loaders": [{"loaderId": 20, "waitingTruckCount": 5}],
        },
        observed_at=observed_at or INCIDENT,
    )


def _sanitize(trigger: InvestigationTrigger, statement: str, *, depth: int = 1, evidence=None):
    state = initial_state(trigger, max_iterations=3, provider="mock", model="mock")
    state["evidence"] = [evidence or _evidence()]
    diagnosis = DiagnosisResult(
        hypotheses=[
            Hypothesis(
                hypothesis_id="hyp-1",
                statement=statement,
                supporting_evidence_ids=["ev-causal"],
                confidence=ConfidenceLevel.HIGH,
                causal_depth=depth,
                rationale="The cited evidence is proposed as causal support.",
            )
        ],
        can_conclude=True,
        confidence=ConfidenceLevel.HIGH,
        confidence_rationale="One proposed mechanism dominates.",
        reasoning_summary="A structured causal hypothesis was evaluated.",
    )
    diagnosis = InvestigationNodes._sanitize_diagnosis(diagnosis, state)
    state["diagnosis"] = diagnosis
    state["hypotheses"] = diagnosis.hypotheses
    conclusion = InvestigationConclusion(
        summary=statement,
        diagnosis_status=DiagnosisStatus.PROBABLE,
        root_cause=statement,
        reliable_root_cause=False,
        derived_metric_evidence_ids=["ev-causal"],
        supported_hypothesis_ids=["hyp-1"],
        confidence=ConfidenceLevel.HIGH,
    )
    return diagnosis, InvestigationNodes._sanitize_conclusion(conclusion, state)


@pytest.mark.parametrize(
    ("trigger", "statement"),
    [
        (
            _trigger(TriggerType.CONGESTION_RISK, "TRK-004 remained in WAITING_LOADING for 25 minutes."),
            "Prolonged waiting was caused by the truck waiting too long.",
        ),
        (
            _trigger(TriggerType.PRODUCTION_DEVIATION, "Production is 18% below target."),
            "Low production was caused by low production.",
        ),
        (
            _trigger(TriggerType.EQUIPMENT_ANOMALY, "Fuel rate is abnormally high."),
            "High fuel consumption was caused by high fuel consumption.",
        ),
    ],
)
def test_symptom_restatement_cannot_be_probable(trigger, statement):
    diagnosis, conclusion = _sanitize(trigger, statement)

    assert diagnosis.hypotheses[0].causal_depth == 0
    assert diagnosis.hypotheses[0].confidence == ConfidenceLevel.LOW
    assert conclusion.diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    assert conclusion.root_cause is None


def test_deeper_loading_mechanism_can_be_probable():
    trigger = _trigger(
        TriggerType.CONGESTION_RISK,
        "TRK-004 remained in WAITING_LOADING for 25 minutes.",
    )
    statement = "Degraded loader service rate at the loading point caused the shared truck queue."

    diagnosis, conclusion = _sanitize(trigger, statement, depth=2)

    assert diagnosis.hypotheses[0].causal_depth == 2
    assert conclusion.diagnosis_status == DiagnosisStatus.PROBABLE
    assert conclusion.causal_depth == 2
    assert conclusion.reliable_root_cause is False


def test_post_event_evidence_does_not_support_probable_cause():
    trigger = _trigger(TriggerType.EQUIPMENT_ANOMALY, "The truck stopped mechanically.")
    evidence = EvidenceItem(
        evidence_id="ev-causal",
        kind=EvidenceKind.FACT,
        source_tool="site_alerts",
        source_service="app.services.operational.alerts.list_site_alerts",
        metric="active_site_alerts",
        value={"occurredAt": (INCIDENT + timedelta(minutes=5)).isoformat()},
        observed_at=INCIDENT + timedelta(minutes=5),
    )

    _, conclusion = _sanitize(
        trigger,
        "A lubrication-related oil-pressure loss caused the mechanical stop.",
        depth=2,
        evidence=evidence,
    )

    assert conclusion.diagnosis_status == DiagnosisStatus.INCONCLUSIVE


def test_correlated_communication_loss_is_not_a_mechanical_root_cause():
    trigger = _trigger(TriggerType.EQUIPMENT_ANOMALY, "The truck stopped mechanically.")
    statement = "A nearby communication loss caused the mechanical stop."

    assert is_symptom_restatement(statement, trigger)
    _, conclusion = _sanitize(trigger, statement)
    assert conclusion.diagnosis_status == DiagnosisStatus.INCONCLUSIVE
