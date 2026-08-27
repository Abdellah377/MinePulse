"""Evaluation catalog based on operational conditions available in dev data.

Scenario names and ground truth are evaluation metadata only.  Case execution
resolves ordinary persisted equipment/site/shift identifiers and sends only a
normal :class:`InvestigationTrigger` to production code.
"""

from app.ai.contracts import ConfidenceLevel, EvidenceKind, EvidenceRequestType, TriggerType

from ai_eval.contracts import (
    EvaluationCase,
    EvaluationGroundTruth,
    EvaluationLevel,
    GroundTruthLabel,
)


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
            scenario_name="ambiguous_stop",
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
    "causal_lubrication_degradation": EvaluationCase(
        case_id="causal_lubrication_degradation",
        description="Progressive low-oil-pressure symptoms preceding a mechanical stop.",
        equipment_code="TRK-001",
        trigger_type=TriggerType.MAINTENANCE_RISK,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.LUBRICATION_DEGRADATION,
            summary="A lubrication-system degradation drove oil pressure down before the stop.",
            scenario_name="lubrication_degradation",
            reviewer_notes="Accept lubrication/oil-pressure diagnosis; reject unsupported named components.",
        ),
        expected_evidence_tools=["fleet_snapshot", "site_alerts", "oem_diagnostics"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["lubrication", "oil pressure", "pression d'huile", "huile"]],
        forbidden_concepts=["oil pump fracture", "bearing seizure", "filter rupture"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.OEM_DIAGNOSTICS,
        evaluation_level=EvaluationLevel.ROOT_CAUSE_DIAGNOSIS,
        requires_temporal_evidence=True,
        temporal_signal_patterns=["oil_pressure_kpa"],
        temporal_direction="DECREASING",
    ),
    "causal_cooling_degradation": EvaluationCase(
        case_id="causal_cooling_degradation",
        description="Progressive thermal rise and derating preceding a mechanical stop.",
        equipment_code="TRK-002",
        trigger_type=TriggerType.MAINTENANCE_RISK,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.COOLING_DEGRADATION,
            summary="Cooling performance degraded and temperatures rose before the stop.",
            scenario_name="cooling_degradation",
        ),
        expected_evidence_tools=["fleet_snapshot", "site_alerts", "oem_diagnostics"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["cooling", "overheat", "surchauff", "temperature"]],
        forbidden_concepts=["radiator rupture", "water pump fracture", "coolant leak confirmed"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.OEM_DIAGNOSTICS,
        evaluation_level=EvaluationLevel.ROOT_CAUSE_DIAGNOSIS,
        requires_temporal_evidence=True,
        temporal_signal_patterns=["engine_temp_c", "coolant_temp_c"],
        temporal_direction="INCREASING",
    ),
    "causal_tyre_degradation": EvaluationCase(
        case_id="causal_tyre_degradation",
        description="Progressive tyre pressure/temperature degradation preceding a safe stop.",
        equipment_code="TRK-003",
        trigger_type=TriggerType.MAINTENANCE_RISK,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.TYRE_DEGRADATION,
            summary="A progressive tyre condition led to a controlled stop.",
            scenario_name="tyre_degradation",
        ),
        expected_evidence_tools=["fleet_snapshot", "site_alerts", "oem_errors"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["tyre", "tire", "pneu", "pressure", "pression"]],
        forbidden_concepts=["blowout confirmed", "rim fracture", "brake failure"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.OEM_ERRORS,
        evaluation_level=EvaluationLevel.ROOT_CAUSE_DIAGNOSIS,
        requires_temporal_evidence=True,
        temporal_signal_patterns=["_pressure"],
        temporal_direction="DECREASING",
    ),
    "causal_communication_degradation": EvaluationCase(
        case_id="causal_communication_degradation",
        description="Link quality degradation and intermittent gaps preceding connection loss.",
        equipment_code="TRK-004",
        trigger_type=TriggerType.CONNECTIVITY_ISSUE,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.COMMUNICATION_DEGRADATION,
            summary="Communications quality degraded before telemetry was lost.",
            scenario_name="communication_degradation",
        ),
        expected_evidence_tools=["fleet_snapshot", "site_alerts", "oem_connectivity"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["communication", "connectivity", "connexion", "telemetry", "télémétrie"]],
        forbidden_concepts=["confirmed mechanical failure", "engine failure", "hydraulic failure"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.OEM_CONNECTIVITY,
        evaluation_level=EvaluationLevel.ROOT_CAUSE_DIAGNOSIS,
        requires_temporal_evidence=True,
        temporal_signal_patterns=["communication_quality"],
        temporal_direction="DECREASING",
    ),
    "causal_loader_bottleneck": EvaluationCase(
        case_id="causal_loader_bottleneck",
        description="Loader throughput degrades, increasing queues and cycle times across trucks.",
        equipment_code="EXC-001",
        trigger_type=TriggerType.CONGESTION_RISK,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.OPERATIONAL_BOTTLENECK,
            summary="Loader performance degradation created a cross-fleet loading bottleneck.",
            scenario_name="loader_bottleneck",
            reviewer_notes="This case should be diagnosed from shared operational effects, not maintenance telemetry.",
        ),
        expected_evidence_tools=["fleet_snapshot", "cycle_performance", "assignments"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["loader", "loading", "chargement"], ["queue", "waiting", "attente", "bottleneck"]],
        forbidden_concepts=["mechanical failure confirmed", "hydraulic pump failure", "optimized dispatch"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.ASSIGNMENTS,
        evaluation_level=EvaluationLevel.ROOT_CAUSE_DIAGNOSIS,
        requires_temporal_evidence=False,
    ),
    "causal_fuel_efficiency_degradation": EvaluationCase(
        case_id="causal_fuel_efficiency_degradation",
        description="Fuel rate rises relative to load while performance and cycle behavior degrade.",
        equipment_code="TRK-001",
        trigger_type=TriggerType.MAINTENANCE_RISK,
        ground_truth=EvaluationGroundTruth(
            label=GroundTruthLabel.FUEL_EFFICIENCY_DEGRADATION,
            summary="Fuel efficiency degraded progressively under comparable operating load.",
            scenario_name="fuel_efficiency_degradation",
            reviewer_notes="Accept a fuel-efficiency anomaly; reject an unsupported named component.",
        ),
        expected_evidence_tools=["fleet_snapshot", "cycle_performance", "oem_diagnostics"],
        expected_evidence_kinds=[EvidenceKind.FACT, EvidenceKind.DERIVED_METRIC],
        expected_concept_groups=[["fuel", "carburant", "consumption", "consommation"]],
        forbidden_concepts=["injector failure confirmed", "fuel leak confirmed", "engine rebuild"],
        expected_reliable_root_cause=True,
        expected_confidence=ConfidenceLevel.HIGH,
        mock_request_type=EvidenceRequestType.OEM_DIAGNOSTICS,
        evaluation_level=EvaluationLevel.ROOT_CAUSE_DIAGNOSIS,
        requires_temporal_evidence=True,
        temporal_signal_patterns=["fuel_rate_lph"],
        temporal_direction="INCREASING",
    ),
}


def get_case(case_id: str) -> EvaluationCase:
    try:
        return EVALUATION_CASES[case_id]
    except KeyError as exc:
        choices = ", ".join(sorted(EVALUATION_CASES))
        raise ValueError(f"Unknown evaluation case {case_id!r}; choose one of: {choices}") from exc
