"""Opt-in persisted-data evaluations; normal pytest execution spends $0."""

from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from ai_eval.cases import EVALUATION_CASES
from ai_eval.runner import run_evaluation
from app.ai.contracts import EvidenceRequest, EvidenceRequestType
from app.ai.persistence import get_investigation
from app.ai.tools import oem as ai_oem_tools
from app.db.database import SessionLocal
from app.db.models import Equipment, EquipmentTelemetry, Site
from app.oem import queries as oem_queries
from app.services.operational.context import get_operational_context
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
        if ground_truth.scenario_name:
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
        trends = oem_queries.get_equipment_signal_trends(
            session,
            "TRK-001",
            run.started_at.isoformat(),
            run.incident_at.isoformat(),
            ["oil_pressure_kpa", "engine_temp_c", "fuel_rate_lph"],
            site_id=equipment.site_id,
        )
        oil_trend = next(
            item for item in trends["metrics"] if item["metric"] == "oil_pressure_kpa"
        )
        assert oil_trend["direction"] == "falling"
        assert 3 <= oil_trend["sampleCount"]
        assert len(oil_trend["representativeSamples"]) <= 8
        first_observed = datetime.fromisoformat(oil_trend["firstObservedAt"])
        last_observed = datetime.fromisoformat(oil_trend["lastObservedAt"])
        assert first_observed < last_observed <= run.incident_at

        site = session.get(Site, equipment.site_id)
        assert site is not None
        ctx = get_operational_context(session, site_code=site.code)
        trend_evidence = ai_oem_tools.telemetry_trends(
            session,
            ctx,
            EvidenceRequest(
                request_type=EvidenceRequestType.EQUIPMENT_TELEMETRY_TRENDS,
                equipment_id=equipment.equipment_id,
                start_time=run.started_at,
                end_time=run.incident_at,
                parameters=["mechanical"],
                reason="Verify persisted pre-incident telemetry.",
            ),
        )
        assert trend_evidence.available
        assert trend_evidence.metadata["preIncidentSampleCount"] >= 3
        assert "scenario" not in trend_evidence.model_dump_json().casefold()

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
        report_trend = next(
            item for item in report.evidence if item.source_tool == "equipment_telemetry_trends"
        )
        assert report_trend.available


@pytest.mark.ai_eval
@requires_integration
def test_fuel_sabotage_persists_bounded_load_aware_history_for_ai():
    """The fuel case exposes observations, never the simulator's hidden profile."""
    from simulator.engine import SimulationEngine

    with SessionLocal() as session:
        try:
            engine = SimulationEngine(session)
        except RuntimeError as exc:
            pytest.skip(f"simulator seed is unavailable: {exc}")
        equipment = session.scalar(select(Equipment).where(Equipment.code == "TRK-016"))
        if equipment is None:
            pytest.skip("TRK-016 is not seeded")
        command = SimulationCommand.create(
            target_type="EQUIPMENT",
            target_id="TRK-016",
            action="FUEL_RATE_HIGH",
            parameters={"seed": 1616},
        )
        injection = _apply_command(engine._command_ctx(), command)
        assert injection is not None
        run = engine.causal_scenarios.active[injection.original_state["causal_run_id"]]
        engine.start()
        ticks = math.ceil(run.duration_sec / (engine.cfg.tick_seconds * engine.clock.speed)) + 3
        for _ in range(ticks):
            engine.tick()
        engine.pause()

        trends = oem_queries.get_equipment_signal_trends(
            session,
            "TRK-016",
            run.started_at.isoformat(),
            run.incident_at.isoformat(),
            ["fuel_rate_lph", "engine_load_pct", "speed_kmh", "payload_t", "engine_temp_c"],
            site_id=equipment.site_id,
        )
        by_metric = {item["metric"]: item for item in trends["metrics"]}
        assert by_metric["fuel_rate_lph"]["sampleCount"] >= 3
        assert by_metric["fuel_rate_lph"]["max"] > by_metric["fuel_rate_lph"]["min"]
        assert by_metric["engine_load_pct"]["sampleCount"] >= 3
        assert all(
            len(item["representativeSamples"]) <= 8 for item in trends["metrics"]
        )
        serialized = str(trends).casefold()
        assert "fuel_efficiency_degradation" not in serialized
        assert "hidden" not in serialized

        report = run_evaluation(session, "causal_fuel_efficiency_degradation")
        report_trend = next(
            item for item in report.evidence if item.source_tool == "equipment_telemetry_trends"
        )
        assert report_trend.available
