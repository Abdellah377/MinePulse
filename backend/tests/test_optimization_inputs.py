from app.optimization.contracts import payload_contains_forbidden_numeric_facts
from app.optimization.inputs import TrustedOptimizationInput
from app.optimization.registry import catalog_for_planner


def test_trusted_planner_facts_never_include_wait_travel_or_score():
    facts = {
        "alertType": "CONGESTION_RISK",
        "detectorId": "prolonged-idle-wait",
        "siteId": 1,
        "siteCode": "MP-SIM-01",
        "shiftId": 2,
        "zoneId": 3,
        "zoneCode": "L1",
        "equipmentId": 9,
        "equipmentCode": "TRK-020",
        "equipmentType": "HAUL_TRUCK",
        "equipmentState": "WAITING_LOADING",
        "hasQueueCondition": True,
        "hasRoadRestrictionOrBlockage": False,
        "hasMechanicalRiskAlert": False,
        "registeredOptimizers": ["DISPATCH_LOADER", "ROUTE"],
        "optimizerCatalog": catalog_for_planner(),
        "evidenceIds": ["alert-1"],
    }
    assert payload_contains_forbidden_numeric_facts(facts) is False
    trusted = TrustedOptimizationInput(
        truck=None,
        assignment=None,
        loaders=[],
        roads=[],
        zone_codes={},
        loading={"loaders": [{"loaderId": 1, "waitingTruckCount": 2, "waitingTrucks": [{"waitingMinutes": 8}]}]},
        origin_code=None,
        dest_code=None,
        loader_zones={},
        candidate_loader_ids=[],
        mechanical_risk_loader_ids=set(),
        planner_facts=facts,
        snapshot_fields={},
    )
    dumped = trusted.as_engine_dict()
    assert "waitingTruckCount" in dumped["loading"]["loaders"][0]
    assert "waitMinutes" not in facts
    assert "travelMinutes" not in facts
    assert "score" not in facts
