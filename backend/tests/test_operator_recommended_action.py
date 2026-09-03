from pathlib import Path

from app.optimization.compose import (
    INSUFFICIENT_DATA_ACTION_COPY,
    NO_CHANGE_ACTION_COPY,
    NO_FEASIBLE_ACTION_COPY,
    compose_operator_recommended_action,
)


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


def test_not_applicable_to_dispatch_uses_investigation_not_unknown_truck():
    action = compose_operator_recommended_action(
        eligibility="OPTIMIZABLE",
        outcome="NOT_APPLICABLE_TO_DISPATCH",
        operator_summary=None,
        recommended=None,
        investigation_description="Vérifier le concasseur.",
    )
    assert action == {"text": "Vérifier le concasseur.", "source": "investigation"}
    assert "Camion sujet" not in action["text"]


def test_insufficient_data_is_truthful_status_not_an_invented_action():
    action = compose_operator_recommended_action(
        eligibility="OPTIMIZABLE",
        outcome="INSUFFICIENT_DATA",
        operator_summary=None,
        recommended=None,
        investigation_description="Inventer un reroutage.",
    )
    assert action == {"text": INSUFFICIENT_DATA_ACTION_COPY, "source": "optimizer"}
    assert "Réaffecter" not in action["text"]


def test_feasible_action_uses_truck_loader_dest_and_ignores_score_summary():
    action = compose_operator_recommended_action(
        eligibility="OPTIMIZABLE",
        outcome="FEASIBLE",
        operator_summary="Score = 1 × travel (8 min) + 1 × attente (4 min). Météo affichée, non notée. Acceptation ≠ application FMS.",
        recommended={
            "truckCode": "TRK-011",
            "loaderCode": "LDR-001",
            "destZoneCode": "DUMP_N",
            "originZoneCode": "PIT_A",
        },
        investigation_description="Vérifier la file Banc A.",
    )
    assert action["source"] == "optimizer"
    assert action["text"] == "Réaffecter TRK-011 vers LDR-001 → DUMP_N."
    assert "Score =" not in action["text"]
    assert "Vérifier la file" not in action["text"]


def test_no_change_and_no_feasible_copy():
    no_change = compose_operator_recommended_action(
        eligibility="OPTIMIZABLE",
        outcome="FEASIBLE",
        operator_summary="Score = 1 × travel (3 min) + 1 × attente (0 min).",
        recommended={"truckCode": "TRK-1", "loaderCode": "LD-1", "destZoneCode": "D1", "isCurrent": True},
        investigation_description=None,
        workflow_status="NO_CHANGE_RECOMMENDED",
    )
    assert no_change == {"text": NO_CHANGE_ACTION_COPY, "source": "optimizer"}
    no_feasible = compose_operator_recommended_action(
        eligibility="OPTIMIZABLE",
        outcome="NO_FEASIBLE_PLAN",
        operator_summary=None,
        recommended=None,
        investigation_description="Isoler EXC-002.",
    )
    assert no_feasible == {"text": NO_FEASIBLE_ACTION_COPY, "source": "optimizer"}


def test_rca_lookup_imports_find_investigations():
    source = (Path(__file__).resolve().parents[1] / "app" / "ai" / "optimization" / "workflow.py").read_text(encoding="utf-8")
    assert "from app.ai.persistence import find_investigations" in source
    assert "rows = find_investigations(" in source.split("def _rca_from_investigation")[1].split("def ")[0]
