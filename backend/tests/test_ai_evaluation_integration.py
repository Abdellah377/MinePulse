"""Opt-in persisted-data evaluations; normal pytest execution spends $0."""

from __future__ import annotations

from uuid import UUID

import pytest

from ai_eval.cases import EVALUATION_CASES
from ai_eval.runner import run_evaluation
from app.ai.persistence import get_investigation
from app.db.database import SessionLocal


requires_integration = pytest.mark.skipif(
    "not config.getoption('--integration')",
    reason="persisted-data evaluation requires --integration and DATABASE_URL",
)
requires_real_ai = pytest.mark.skipif(
    "not config.getoption('--run-ai')",
    reason="real provider evaluation is opt-in with --run-ai and may incur API charges",
)


@pytest.mark.ai_eval
@requires_integration
@pytest.mark.parametrize("case_id", sorted(EVALUATION_CASES))
def test_mocked_provider_runs_real_persisted_operational_stack(case_id):
    with SessionLocal() as session:
        try:
            report = run_evaluation(session, case_id)
        except LookupError as exc:
            pytest.skip(f"evaluation data is not prepared: {exc}")
        assert report.pipeline_correct
        assert report.reasoning_mode == "MOCKED_PIPELINE"
        assert report.investigation_id
        assert report.iteration_count == 2
        assert report.evidence_request_history
        assert get_investigation(session, UUID(report.investigation_id)) is not None
        assert report.evidence
        assert all(
            item.source_service.startswith(("app.services.operational", "app.oem"))
            for item in report.evidence
            if item.available
        )
        serialized_trigger = report.trigger.model_dump_json().casefold()
        ground_truth = EVALUATION_CASES[case_id].ground_truth
        assert ground_truth.scenario_name not in serialized_trigger
        assert ground_truth.label.value.casefold() not in serialized_trigger


@pytest.mark.ai_eval
@pytest.mark.real_ai
@requires_integration
@requires_real_ai
def test_one_persisted_case_against_configured_real_provider():
    """Explicitly paid: exactly one investigation when both flags are supplied."""
    with SessionLocal() as session:
        report = run_evaluation(session, "clear_equipment_failure", real_llm=True)
    assert report.pipeline_correct
    assert report.reasoning_mode == "REAL_LLM"
