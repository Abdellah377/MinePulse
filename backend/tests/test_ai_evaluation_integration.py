"""Opt-in persisted-data evaluations; normal pytest execution spends $0."""

from __future__ import annotations

import math
from uuid import UUID

import pytest
from sqlalchemy import select

from ai_eval.cases import EVALUATION_CASES
from ai_eval.runner import run_evaluation
from app.ai.persistence import get_investigation
from app.db.database import SessionLocal
from app.db.models import Equipment, EquipmentTelemetry
from simulator.apply_commands import _apply_command
from simulator.commands import SimulationCommand


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


@pytest.mark.ai_eval
@requires_integration
def test_causal_scenario_persists_observable_evidence_before_evaluation():
    """Opt-in setup uses simulator; investigation still uses only DB/services."""
    from simulator.engine import SimulationEngine

    with SessionLocal() as session:
        try:
            engine = SimulationEngine(session)
        except RuntimeError as exc:
            pytest.skip(f"simulator seed is unavailable: {exc}")
        equipment = session.scalar(select(Equipment).where(Equipment.code == "TRK-001"))
        if equipment is None:
            pytest.skip("TRK-001 is not seeded")
        command = SimulationCommand.create(
            target_type="EQUIPMENT",
            target_id="TRK-001",
            action="MECHANICAL_BREAKDOWN",
            parameters={"seed": 2026, "profile": "lubrication"},
        )
        injection = _apply_command(engine._command_ctx(), command)
        assert injection is not None
        run = engine.causal_scenarios.active[injection.original_state["causal_run_id"]]
        assert not engine.world.trucks["TRK-001"].mechanical_hold
        engine.start()
        ticks = math.ceil(run.duration_sec / (engine.cfg.tick_seconds * engine.clock.speed)) + 3
        for _ in range(ticks):
            engine.tick()
        engine.pause()
        assert engine.world.trucks["TRK-001"].mechanical_hold
        telemetry = session.scalars(
            select(EquipmentTelemetry)
            .where(
                EquipmentTelemetry.equipment_id == equipment.equipment_id,
                EquipmentTelemetry.ts >= run.started_at,
            )
            .order_by(EquipmentTelemetry.ts)
        ).all()
        oil_values = [float(row.oil_pressure_kpa) for row in telemetry if row.oil_pressure_kpa is not None]
        assert len(oil_values) >= 3
        assert oil_values[-1] < oil_values[0]

        report = run_evaluation(session, "causal_lubrication_degradation")
        assert report.pipeline_correct
        assert report.quality_levels["LEVEL_1_INTEGRATION"] is True
        assert report.quality_levels["LEVEL_3_ROOT_CAUSE_DIAGNOSIS"] is None
        assert all(
            item.source_service.startswith(("app.services.operational", "app.oem"))
            for item in report.evidence
            if item.available
        )
        serialized_trigger = report.trigger.model_dump_json().casefold()
        assert "lubrication_degradation" not in serialized_trigger
        assert "lubrication_system_degradation" not in serialized_trigger
