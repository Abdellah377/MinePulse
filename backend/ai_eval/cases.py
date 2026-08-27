"""Evaluation catalog based on operational conditions available in dev data.

Scenario names and ground truth are evaluation metadata only.  Case execution
resolves ordinary persisted equipment/site/shift identifiers and sends only a
normal :class:`InvestigationTrigger` to production code.
"""

from app.ai.contracts import ConfidenceLevel, EvidenceKind, EvidenceRequestType, TriggerType

from ai_eval.contracts import EvaluationCase, EvaluationGroundTruth, GroundTruthLabel


EVALUATION_CASES: dict[str, EvaluationCase] = {
    "clear_equipment_failure": EvaluationCase(
        case_id="clear_equipment_failure",
        description="Equipment stop with persisted breakdown and maintenance signals.",
        equipment_code="EXC-002",
        trigger_type=TriggerType.EQUIPMENT_ANOMALY,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.MECHANICAL_FAILURE,
            summary="The equipment experienced a mechanical breakdown.",
            scenario_name="exc_breakdown",
            reviewer_notes="A sub-component is valid only if a persisted record names it.",
        ),
        expected_evidence_tools=[
            "fleet_snapshot",
            "site_alerts",
            "oem_maintenance_indicators",
        ],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["mechanical", "mécanique", "breakdown", "failure", "panne"]],
        forbidden_concepts=["engine fire", "transmission failure", "brake failure"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.OEM_MAINTENANCE_INDICATORS,
    ),
    "connectivity_loss": EvaluationCase(
        case_id="connectivity_loss",
        description="Equipment communication loss without confirmed mechanical failure.",
        equipment_code="TRK-004",
        trigger_type=TriggerType.CONNECTIVITY_ISSUE,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.CONNECTIVITY_LOSS,
            summary="Telemetry communication was lost or degraded.",
            scenario_name="comm_loss",
        ),
        expected_evidence_tools=["fleet_snapshot", "site_alerts", "oem_connectivity"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[
            ["communication", "connectivity", "connexion", "telemetry", "télémétrie"]
        ],
        forbidden_concepts=["confirmed mechanical failure", "hydraulic failure", "engine failure"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.OEM_CONNECTIVITY,
    ),
    "ambiguous_stop": EvaluationCase(
        case_id="ambiguous_stop",
        description="An equipment stop with insufficient evidence for a reliable cause.",
        equipment_code="TRK-012",
        trigger_type=TriggerType.EQUIPMENT_ANOMALY,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.UNEXPLAINED_STOP,
            summary="The equipment stopped, but the cause is not established.",
            scenario_name="unexplained_stop",
        ),
        expected_evidence_tools=["fleet_snapshot", "site_alerts", "equipment_timeline"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["stop", "stopped", "arrêt", "immobilisé"]],
        forbidden_concepts=["confirmed mechanical failure", "hydraulic failure", "engine failure"],
        expected_reliable_root_cause=False,
        expected_confidence=ConfidenceLevel.LOW,
        inconclusive_acceptable=True,
        mock_request_type=EvidenceRequestType.EQUIPMENT_TIMELINE,
    ),
}


def get_case(case_id: str) -> EvaluationCase:
    try:
        return EVALUATION_CASES[case_id]
    except KeyError as exc:
        choices = ", ".join(sorted(EVALUATION_CASES))
        raise ValueError(f"Unknown evaluation case {case_id!r}; choose one of: {choices}") from exc
