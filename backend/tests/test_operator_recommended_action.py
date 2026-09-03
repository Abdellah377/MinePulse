from app.optimization.compose import compose_operator_recommended_action


def test_optimizable_feasible_plan_is_the_only_action():
    action = compose_operator_recommended_action(
        eligibility="OPTIMIZABLE",
        outcome="FEASIBLE",
        operator_summary="Réaffecter vers LD-2 → DUMP_N.",
        recommended={"loaderCode": "LD-2", "destZoneCode": "DUMP_N"},
        investigation_description="Vérifier la file Banc A.",
    )
    assert action["source"] == "optimizer"
    assert "LD-2" in action["text"]
    assert "Vérifier la file" not in action["text"]


def test_not_applicable_uses_investigation_recommendation():
    action = compose_operator_recommended_action(
        eligibility="NOT_APPLICABLE",
        outcome="NOT_APPLICABLE",
        operator_summary=None,
        recommended=None,
        investigation_description="Isoler EXC-002 jusqu’à confirmation maintenance.",
    )
    assert action["source"] == "investigation"
    assert "EXC-002" in action["text"]


def test_no_plan_no_investigation_has_no_action_text():
    action = compose_operator_recommended_action(
        eligibility="OPTIMIZABLE",
        outcome="INSUFFICIENT_DATA",
        operator_summary=None,
        recommended=None,
        investigation_description=None,
    )
    assert action["text"] is None
    assert action["source"] is None
