from app.ai.optimization.planner import planner_payload_from_facts, sanitize_planner_decision
from app.optimization.contracts import (
    FORBIDDEN_PLANNER_NUMERIC_KEYS,
    OptimizationPlannerDecision,
    OptimizerId,
    ProblemType,
    payload_contains_forbidden_numeric_facts,
)
from app.optimization.registry import catalog_for_planner


def test_planner_facts_reject_numeric_optimizer_keys():
    dirty = {"waitMinutes": 12, "alertType": "CONGESTION_RISK"}
    assert payload_contains_forbidden_numeric_facts(dirty)
    clean = {
        "alertType": "CONGESTION_RISK",
        "hasQueueCondition": True,
        "hasRoadRestrictionOrBlockage": False,
        "hasMechanicalRiskAlert": False,
        "registeredOptimizers": ["DISPATCH_LOADER", "ROUTE"],
        "optimizerCatalog": catalog_for_planner(),
        "evidenceIds": ["alert-1"],
    }
    assert payload_contains_forbidden_numeric_facts(clean) is False
    for key in FORBIDDEN_PLANNER_NUMERIC_KEYS:
        assert key not in clean


def test_planner_payload_strips_smuggled_metrics():
    payload = planner_payload_from_facts(
        {
            "alertType": "CONGESTION_RISK",
            "waitMinutes": 9,
            "score": 4.7,
            "hasQueueCondition": True,
            "evidenceIds": ["alert-1"],
            "optimizerCatalog": catalog_for_planner(),
        }
    )
    assert "waitMinutes" not in payload
    assert "score" not in payload
    assert payload["hasQueueCondition"] is True
    assert payload_contains_forbidden_numeric_facts(payload) is False


def test_sanitize_planner_drops_unknown_engine_and_defaults():
    facts = {
        "alertType": "CONGESTION_RISK",
        "evidenceIds": ["alert-1", "src-9"],
        "hasRoadRestrictionOrBlockage": True,
        "optimizerCatalog": catalog_for_planner(),
    }
    decision = OptimizationPlannerDecision(
        selected_optimizers=[],
        objectives=[],
        relevant_evidence_ids=["alert-1", "invented"],
        requested_constraint_checks=[],
        problem_type=ProblemType.CONGESTION_RISK,
    )
    sanitized, rejected = sanitize_planner_decision(decision, facts=facts)
    assert sanitized.selected_optimizers[0] == OptimizerId.DISPATCH_LOADER
    assert OptimizerId.ROUTE in sanitized.selected_optimizers
    assert len(sanitized.selected_optimizers) <= 2
    assert "alert-1" in sanitized.relevant_evidence_ids
    assert "invented" not in sanitized.relevant_evidence_ids
    assert any("evidence" in item for item in rejected)
    dumped = sanitized.model_dump(mode="json")
    assert payload_contains_forbidden_numeric_facts(dumped) is False
