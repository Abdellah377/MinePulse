import json
from types import SimpleNamespace

from app.ai.contracts import (
    ConfidenceLevel,
    DiagnosisStatus,
    EvidenceItem,
    EvidenceKind,
    EvidenceRequest,
    EvidenceRequestType,
    EvidenceStatus,
    InvestigationConclusion,
    InvestigationResult,
    InvestigationStatus,
)
from app.ai.debug import (
    DebugEventType,
    InvestigationDebugRecorder,
    NullDebugRecorder,
    compact_evidence,
    create_debug_recorder,
    redact,
)
from app.ai.llm.provider import ProviderTimeoutError
from app.ai.tools.registry import EvidenceToolRegistry
from app.config import Settings
from test_ai_graph import FakeTools, ScriptedProvider, _ctx, _diagnosis, _evidence, _run


def _types(dump) -> list[str]:
    return [event["event_type"] for event in dump["events"]]


def test_debug_flag_defaults_false():
    assert Settings.model_fields["ai_debug_mode"].default is False


def test_disabled_recorder_is_noop():
    recorder = create_debug_recorder(enabled=False, investigation_id="inv-1")
    assert isinstance(recorder, NullDebugRecorder)
    recorder.record(DebugEventType.LLM_CALL, stage="analyze", summary="should not persist")
    result, _, persisted = _run(ScriptedProvider([_diagnosis()]), debug=recorder)
    assert recorder.finish(result) is None
    assert "debug_trace" not in persisted[0]


def test_enabled_trace_is_ordered_and_bounded():
    recorder = InvestigationDebugRecorder("inv-1", model="mock-structured")
    result, _, _ = _run(ScriptedProvider([_diagnosis()]), debug=recorder)
    dump = recorder.last_dump
    assert dump is not None
    types = _types(dump)
    assert types[0] == "CONTEXT_RESOLVED"
    assert "INITIAL_EVIDENCE_GATHERED" in types
    assert "LLM_CALL" in types
    assert "HYPOTHESIS_EVALUATED" in types
    assert "ROUTER_DECISION" in types
    assert "VALIDATION_CHECK" in types
    assert "CONCLUSION_BUILT" in types
    assert types[-1] == "INVESTIGATION_COMPLETED"
    assert dump["coverage"]["initial_count"] == 1
    assert dump["stop_reason"] in {"PROBABLE_CAUSE", "INCONCLUSIVE_AFTER_VALIDATION", "CONFIRMED_CAUSE"}
    assert len(dump["events"]) <= 120


def test_additional_request_and_validation_codes_are_visible():
    request = EvidenceRequest(
        request_type=EvidenceRequestType.DOWNTIME,
        reason="Need downtime context before concluding.",
    )
    recorder = InvestigationDebugRecorder("inv-2")
    _run(
        ScriptedProvider([_diagnosis(requests=[request], can_conclude=False), _diagnosis(can_conclude=True)]),
        debug=recorder,
    )
    types = _types(recorder.last_dump)
    assert "ADDITIONAL_EVIDENCE_REQUESTED" in types
    assert "ROUTER_DECISION" in types
    router = next(event for event in recorder.last_dump["events"] if event["event_type"] == "ROUTER_DECISION")
    assert "can_conclude" in router["metadata"]
    assert "iteration_count" in router["metadata"]


def test_cannot_conclude_gate_is_recorded():
    recorder = InvestigationDebugRecorder("inv-3")
    result, _, _ = _run(ScriptedProvider([_diagnosis(can_conclude=False)]), debug=recorder)
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    checks = {item["check_id"]: item for item in recorder.last_dump["validation_checks"]}
    assert checks["DIAGNOSIS_CANNOT_CONCLUDE"]["passed"] is False
    codes = [
        code
        for event in recorder.last_dump["events"]
        if event["event_type"] == "HYPOTHESIS_EVALUATED"
        for code in event["metadata"].get("reason_codes", [])
    ]
    assert "CAUSAL_DEPTH_TOO_LOW" in codes or checks["DIAGNOSIS_CANNOT_CONCLUDE"]["passed"] is False


def test_status_downgrade_probable_to_inconclusive():
    class ProbableThenBlocked(ScriptedProvider):
        def build_conclusion(self, payload):
            return InvestigationConclusion(
                summary="Provider proposed a probable cause.",
                diagnosis_status=DiagnosisStatus.PROBABLE,
                root_cause="Downtime contributed to the shortfall.",
                reliable_root_cause=False,
                derived_metric_evidence_ids=["ev-production"],
                supported_hypothesis_ids=["hyp-1"],
                unresolved_uncertainties=[],
                confidence=ConfidenceLevel.MEDIUM,
            )

    recorder = InvestigationDebugRecorder("inv-4")
    result, _, _ = _run(ProbableThenBlocked([_diagnosis(can_conclude=False)]), debug=recorder)
    assert result["conclusion"].diagnosis_status == DiagnosisStatus.INCONCLUSIVE
    downgrade = next(
        event for event in recorder.last_dump["events"] if event["event_type"] == "STATUS_DOWNGRADED"
    )
    assert "PROBABLE" in downgrade["summary"]
    assert "INCONCLUSIVE" in downgrade["summary"]


def test_provider_failure_is_visible_without_secrets():
    recorder = InvestigationDebugRecorder("inv-5")
    result, _, _ = _run(ScriptedProvider([ProviderTimeoutError("sk-secret-prompt-body")]), debug=recorder)
    assert result["status"] == InvestigationStatus.FAILED
    dump = json.dumps(recorder.last_dump)
    assert recorder.last_dump["stop_reason"] == "PROVIDER_FAILURE"
    assert "PROVIDER_FAILURE" in _types(recorder.last_dump)
    assert "sk-secret-prompt-body" not in dump
    assert "prompt" not in dump
    assert "reasoning_summary" not in dump
    assert "chain_of_thought" not in dump
    assert "api_key" not in dump


def test_tool_success_and_failure_are_recorded_without_values():
    recorder = InvestigationDebugRecorder("inv-6")
    registry = EvidenceToolRegistry(SimpleNamespace(), debug=recorder)
    ctx = _ctx()
    ok = registry._safe_call(ctx, "fleet_snapshot", lambda: _evidence())
    assert ok.available is True
    failed = registry._safe_call(ctx, "oem_diagnostics", lambda: (_ for _ in ()).throw(RuntimeError("secret SQL")))
    assert failed.status == EvidenceStatus.ERROR
    types = [event.event_type for event in recorder._events]
    assert types == [DebugEventType.TOOL_COMPLETED, DebugEventType.TOOL_COMPLETED]
    blob = json.dumps([event.model_dump(mode="json") for event in recorder._events])
    assert "secret SQL" not in blob
    assert ok.value is not None
    assert "tonnage" not in blob or compact_evidence(ok)["preview"] is not None
    assert failed.value is None


def test_evidence_value_is_previewed_not_copied_in_full():
    blob = "Z" * 800

    class HugeTools(FakeTools):
        def gather_initial(self, ctx, trigger):
            item = _evidence()
            return [
                EvidenceItem(
                    evidence_id=item.evidence_id,
                    kind=EvidenceKind.DERIVED_METRIC,
                    source_tool=item.source_tool,
                    source_service=item.source_service,
                    metric=item.metric,
                    value={"payload": blob},
                    site_id=item.site_id,
                    shift_id=item.shift_id,
                    observed_at=item.observed_at,
                )
            ]

    recorder = InvestigationDebugRecorder("inv-7")
    _run(ScriptedProvider([_diagnosis()]), tools=HugeTools(), debug=recorder)
    dump = json.dumps(recorder.last_dump)
    assert blob not in dump
    assert "payload" in dump


def test_redact_drops_secret_and_prompt_keys():
    cleaned = redact({"api_key": "sk", "authorization": "Bearer x", "prompt": "hidden", "ok": 1})
    assert cleaned == {"ok": 1}


def test_operator_result_contract_excludes_debug():
    assert "debug_trace" not in InvestigationResult.model_fields
    assert "debug" not in InvestigationResult.model_fields
