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
    format_investigation_timeline,
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
    assert len(dump["events"]) <= 200
    assert "NODE_TIMING" in types
    nodes = dump["wall_durations_ms"]["nodes"]
    assert "resolve_context" in nodes
    assert "gather_initial_evidence" in nodes
    assert "analyze" in nodes
    assert "build_conclusion" in nodes
    assert "build_recommendation" in nodes
    assert "persist" in nodes
    assert isinstance(dump["wall_durations_ms"]["persist"], int)
    timeline = format_investigation_timeline(dump)
    assert "resolve_context" in timeline
    assert "total_ms=" in timeline
    assert "llm_ms=" in timeline


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


def test_timeline_printer_includes_per_http_attempts_without_secrets():
    dump = {
        "investigation_id": "7f3a9c12-1111-4111-8111-aaaaaaaaaaaa",
        "graph_version": "1.3.0",
        "provider": "gemini",
        "model": "mock",
        "wall_durations_ms": {
            "total": 92140,
            "llm": 91200,
            "evidence": 80,
            "persist": 12,
            "nodes": {
                "resolve_context": 8,
                "gather_initial_evidence": 80,
                "analyze": 91200,
                "build_conclusion": 400,
                "build_recommendation": 420,
                "persist": 12,
            },
        },
        "events": [
            {
                "event_type": "NODE_TIMING",
                "stage": "analyze",
                "duration_ms": 91200,
                "summary": "analyze ok 91200ms",
                "metadata": {"node": "analyze", "status": "ok"},
            },
            {
                "event_type": "LLM_ATTEMPT",
                "stage": "analyze",
                "duration_ms": 45100,
                "summary": "groq timeout 45100ms",
                "metadata": {
                    "stage": "analyze",
                    "provider": "groq",
                    "model": "openai/gpt-oss-120b",
                    "attempt": 1,
                    "http_status_class": "timeout",
                    "failure_category": "ProviderTimeoutError",
                    "parse_retry": False,
                    "prompt_chars": 4200,
                    "evidence_count": 6,
                    "remaining_budget_ms": 104900,
                },
            },
            {
                "event_type": "LLM_ATTEMPT",
                "stage": "analyze",
                "duration_ms": 45000,
                "summary": "groq timeout 45000ms",
                "metadata": {
                    "stage": "analyze",
                    "provider": "groq",
                    "model": "openai/gpt-oss-120b",
                    "attempt": 2,
                    "http_status_class": "timeout",
                    "failure_category": "ProviderTimeoutError",
                    "parse_retry": False,
                    "prompt_chars": 4200,
                    "evidence_count": 6,
                    "remaining_budget_ms": 59900,
                },
            },
            {
                "event_type": "LLM_ATTEMPT",
                "stage": "analyze",
                "duration_ms": 1100,
                "summary": "gemini ok 1100ms",
                "metadata": {
                    "stage": "analyze",
                    "provider": "gemini",
                    "model": "gemini-flash",
                    "attempt": 1,
                    "http_status_class": "ok",
                    "failure_category": None,
                    "parse_retry": False,
                    "prompt_chars": 4200,
                    "evidence_count": 6,
                    "remaining_budget_ms": 58800,
                },
            },
        ],
    }
    text = format_investigation_timeline(dump)
    assert "GRAPH 1.3.0" in text
    assert "total_ms=92140" in text
    assert "persist_ms=12" in text
    assert "groq" in text and "timeout" in text
    assert "gemini" in text
    assert "sk-" not in text
    assert "gsk_" not in text
    groq_share = 90100 / 92140
    assert groq_share > 0.9


def test_graph_emits_llm_attempt_events_from_provider_metrics():
    class AttemptProvider(ScriptedProvider):
        def diagnose(self, payload):
            self.last_call_metrics = {
                "provider": "groq",
                "model": "mock",
                "duration_ms": 80,
                "fallback_occurred": True,
                "remaining_budget_ms": 149920,
                "attempts": [
                    {
                        "provider": "groq",
                        "model": "mock",
                        "attempt": 1,
                        "duration_ms": 50,
                        "http_status_class": "timeout",
                        "failure_category": "ProviderTimeoutError",
                        "parse_retry": False,
                        "prompt_chars": 24,
                        "evidence_count": 1,
                        "remaining_budget_ms": 149950,
                    },
                    {
                        "provider": "gemini",
                        "model": "mock",
                        "attempt": 1,
                        "duration_ms": 30,
                        "http_status_class": "ok",
                        "failure_category": None,
                        "parse_retry": False,
                        "prompt_chars": 24,
                        "evidence_count": 1,
                        "remaining_budget_ms": 149920,
                    },
                ],
            }
            return super().diagnose(payload)

    recorder = InvestigationDebugRecorder("inv-attempts")
    _run(AttemptProvider([_diagnosis()]), debug=recorder)
    dump = recorder.last_dump
    types = _types(dump)
    assert types.count("LLM_ATTEMPT") >= 2
    blob = json.dumps(dump)
    assert "timeout" in blob
    assert "parse_retry" in blob
    assert "prompt_chars" in blob
    assert "sk-" not in blob
    assert dump["wall_durations_ms"]["llm"] >= 80
    assert "LLM_ATTEMPT" in format_investigation_timeline(dump)


def test_mock_failover_timeouts_dominate_timeline_without_sleep():
    from app.ai.llm.provider import ProviderTimeoutError
    from app.ai.llm.router import ProviderRouter
    from test_llm_router import FakeLeaf, _diagnosis as router_diagnosis

    class CostlyTimeout(FakeLeaf):
        def _run(self, method, payload):
            cost = 45.0
            self._remaining_seconds -= cost
            duration_ms = int(cost * 1000)
            self.last_attempt_count = 1
            self.last_call_metrics = {
                "provider": self.provider_name,
                "model": self.model_name,
                "duration_ms": duration_ms,
                "attempts": [
                    {
                        "provider": self.provider_name,
                        "model": self.model_name,
                        "attempt": 1,
                        "duration_ms": duration_ms,
                        "http_status_class": "timeout",
                        "failure_category": "ProviderTimeoutError",
                        "parse_retry": False,
                        "prompt_chars": 12,
                        "evidence_count": 0,
                        "remaining_budget_ms": int(self._remaining_seconds * 1000),
                    }
                ],
            }
            self.invocations += 1
            self.calls.append((method, payload))
            raise ProviderTimeoutError("timeout")

    groq = CostlyTimeout("groq")
    gemini = CostlyTimeout("gemini")
    openai = FakeLeaf("openai", diagnose=router_diagnosis())
    router = ProviderRouter(
        [groq, gemini, openai],
        budget_seconds=150,
        timeout_seconds=45,
        max_leaf_attempts=1,
    )
    router.diagnose({"evidence": []})
    metrics = router.last_call_metrics
    assert metrics["fallback_occurred"] is True
    assert metrics["final_provider"] == "openai"
    attempt_ms = sum(int(item["duration_ms"]) for item in metrics["attempts"])
    assert attempt_ms >= 90_000
    assert openai.invocations == 1
    dump = {
        "investigation_id": "mock-worst-case",
        "graph_version": "1.3.0",
        "wall_durations_ms": {"total": attempt_ms, "llm": attempt_ms, "evidence": 0, "persist": 0, "nodes": {}},
        "events": [
            {
                "event_type": "LLM_ATTEMPT",
                "stage": "analyze",
                "duration_ms": item["duration_ms"],
                "summary": f"{item['provider']} {item['http_status_class']} {item['duration_ms']}ms",
                "metadata": item,
            }
            for item in metrics["attempts"]
        ],
    }
    text = format_investigation_timeline(dump)
    assert "timeout" in text
    assert "90000" in text or "90" in text
