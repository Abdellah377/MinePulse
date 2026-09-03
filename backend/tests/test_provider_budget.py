"""Remaining-budget admission: configured timeout is a cap, not an admission floor."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ai.contracts import (
    ConfidenceLevel,
    DiagnosisResult,
    InvestigationConclusion,
    InvestigationRecommendation,
    RecommendationAction,
)
from app.ai.llm.chat_completions import ChatCompletionsLLMProvider
from app.ai.llm.provider import (
    MIN_USEFUL_ATTEMPT_SECONDS,
    OpenAILLMProvider,
    ProviderTimeoutError,
    attempt_timeout_seconds,
    budget_allows_attempt,
)
from app.ai.llm.router import ProviderRouter, _mark_cooldown, clear_provider_cooldowns
from app.config import Settings


@pytest.fixture(autouse=True)
def _reset_cooldowns():
    clear_provider_cooldowns()
    yield
    clear_provider_cooldowns()


def _diagnosis(**kwargs):
    return DiagnosisResult(
        can_conclude=False,
        confidence=ConfidenceLevel.LOW,
        confidence_rationale=kwargs.get("rationale", "Unknown"),
        reasoning_summary=kwargs.get("summary", "Insufficient evidence"),
    )


def _conclusion():
    return InvestigationConclusion(summary="Bounded conclusion.", confidence=ConfidenceLevel.LOW)


def _recommendation():
    return InvestigationRecommendation(
        action_type=RecommendationAction.CONTINUE_MONITORING,
        description="Continue monitoring the recorded condition.",
        rationale="The remaining budget still allows a short structured recommendation.",
    )


class TimedLeaf:
    def __init__(self, name, *, model="test-model", timeout_seconds=15, costs=None, **handlers):
        self.provider_name = name
        self.model_name = model
        self._timeout_seconds = timeout_seconds
        self._remaining_seconds = 30
        self._max_attempts = 1
        self.last_attempt_count = 0
        self.last_call_metrics = None
        self.calls: list[tuple[str, dict]] = []
        self._handlers = handlers
        self.costs = dict(costs or {})
        self.invocations = 0
        self.records: list[dict] = []

    def _run(self, method: str, payload: dict):
        remaining = float(self._remaining_seconds)
        configured = float(self._timeout_seconds)
        actual = attempt_timeout_seconds(remaining, configured)
        self.records.append(
            {
                "stage": method,
                "provider": self.provider_name,
                "remaining_before": remaining,
                "configured_timeout": configured,
                "actual_timeout": actual,
            }
        )
        spent = min(float(self.costs.get(method, 0.0)), actual)
        self._remaining_seconds = remaining - spent
        self.invocations += 1
        self.calls.append((method, payload))
        self.last_attempt_count = 1
        self.last_call_metrics = {
            "provider": self.provider_name,
            "model": self.model_name,
            "schema": method,
            "duration_ms": int(spent * 1000),
            "attempts": [
                {
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "attempt": 1,
                    "stage": method,
                    "duration_ms": int(spent * 1000),
                    "http_status_class": "ok",
                    "failure_category": None,
                    "parse_retry": False,
                    "prompt_chars": 0,
                    "evidence_count": 0,
                    "configured_timeout_ms": int(configured * 1000),
                    "actual_timeout_ms": int(actual * 1000),
                    "remaining_budget_before_ms": int(remaining * 1000),
                    "remaining_budget_after_ms": int(self._remaining_seconds * 1000),
                    "remaining_budget_ms": int(self._remaining_seconds * 1000),
                    "fallback": False,
                    "cooldown_skipped": False,
                }
            ],
        }
        spec = self._handlers.get(method, self._handlers.get("*"))
        if isinstance(spec, Exception):
            attempts = self.last_call_metrics["attempts"][0]
            attempts["http_status_class"] = "timeout" if isinstance(spec, ProviderTimeoutError) else "error"
            attempts["failure_category"] = type(spec).__name__
            raise spec
        if spec is None:
            raise ProviderTimeoutError(f"{self.provider_name} has no handler")
        return spec

    def diagnose(self, payload):
        return self._run("diagnose", payload)

    def build_conclusion(self, payload):
        return self._run("build_conclusion", payload)

    def build_recommendation(self, payload):
        return self._run("build_recommendation", payload)

    def discuss_recommendation(self, payload):
        return self._run("discuss_recommendation", payload)

    def plan_optimization(self, payload):
        return self._run("plan_optimization", payload)

    def review_optimization(self, payload):
        return self._run("review_optimization", payload)


def test_min_useful_attempt_window_is_documented():
    assert MIN_USEFUL_ATTEMPT_SECONDS == 4.0


def test_fourteen_seconds_remaining_allows_a_call():
    assert budget_allows_attempt(14, 15) is True
    assert attempt_timeout_seconds(14, 15) == 14


def test_eight_seconds_remaining_caps_actual_timeout():
    assert budget_allows_attempt(8, 15) is True
    assert attempt_timeout_seconds(8, 15) == 8
    assert attempt_timeout_seconds(8, 15) <= 8


def test_four_seconds_remaining_is_at_minimum_useful_threshold():
    assert budget_allows_attempt(4, 15) is True
    assert attempt_timeout_seconds(4, 15) == 4


def test_two_seconds_remaining_skips_the_call():
    assert budget_allows_attempt(2, 15) is False
    assert attempt_timeout_seconds(2, 15) == 2


def test_actual_timeout_never_exceeds_remaining_or_configured():
    for remaining, configured in ((14, 15), (8, 15), (30, 15), (9, 15), (4, 15), (1, 15)):
        actual = attempt_timeout_seconds(remaining, configured)
        assert actual <= remaining
        assert actual <= configured


def test_openai_leaf_uses_remaining_budget_as_timeout(monkeypatch):
    import openai

    client = MagicMock()
    client.responses.parse.return_value.output_parsed = _diagnosis()
    monkeypatch.setattr(openai, "OpenAI", MagicMock(return_value=client))
    provider = OpenAILLMProvider(api_key="test-only", model="test-model", timeout_seconds=15, budget_seconds=30)
    provider._remaining_seconds = 14
    provider.diagnose({})
    assert client.responses.parse.call_count == 1
    assert client.responses.parse.call_args.kwargs["timeout"] == 14
    record = (provider.last_call_metrics or {}).get("attempts")[0]
    assert record["stage"] == "diagnose"
    assert record["configured_timeout_ms"] == 15000
    assert record["actual_timeout_ms"] == 14000
    assert record["remaining_budget_before_ms"] == 14000
    assert record["remaining_budget_after_ms"] <= 14000
    assert record["duration_ms"] >= 0
    assert record["failure_category"] is None


def test_chat_leaf_uses_remaining_budget_as_timeout(monkeypatch):
    import openai

    client = MagicMock()
    parsed = _diagnosis()
    client.chat.completions.parse.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, content=None))],
        usage=None,
    )
    monkeypatch.setattr(openai, "OpenAI", MagicMock(return_value=client))
    provider = ChatCompletionsLLMProvider(
        provider_name="groq",
        api_key="test-only",
        model="test-model",
        base_url="https://api.groq.com/openai/v1",
        timeout_seconds=15,
        budget_seconds=30,
        max_attempts=1,
    )
    provider._remaining_seconds = 8
    provider.diagnose({})
    assert client.chat.completions.parse.call_args.kwargs["timeout"] == 8
    record = (provider.last_call_metrics or {}).get("attempts")[0]
    assert record["actual_timeout_ms"] == 8000
    assert record["remaining_budget_before_ms"] == 8000


def test_two_seconds_remaining_does_not_start_openai_http(monkeypatch):
    import openai

    client = MagicMock()
    monkeypatch.setattr(openai, "OpenAI", MagicMock(return_value=client))
    provider = OpenAILLMProvider(api_key="test-only", model="test-model", timeout_seconds=15, budget_seconds=30)
    provider._remaining_seconds = 2
    with pytest.raises(ProviderTimeoutError, match="budget exceeded"):
        provider.diagnose({})
    assert client.responses.parse.call_count == 0


def test_interactive_deadlines_stay_at_fifteen_and_thirty():
    fields = Settings.model_fields
    assert fields["ai_provider_timeout_seconds"].default == 15
    assert fields["ai_investigation_llm_budget_seconds"].default == 30
    assert fields["ai_max_investigation_iterations"].default == 2


def test_diagnose_can_consume_most_budget_and_conclusion_still_runs():
    groq = TimedLeaf(
        "groq",
        costs={"diagnose": 11, "build_conclusion": 3, "build_recommendation": 2},
        diagnose=_diagnosis(),
        build_conclusion=_conclusion(),
        build_recommendation=_recommendation(),
    )
    router = ProviderRouter([groq], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    router.diagnose({})
    assert groq.records[0]["actual_timeout"] == 15
    router.diagnose({})
    assert groq.records[1]["remaining_before"] == pytest.approx(19)
    router.build_conclusion({})
    conclusion = groq.records[2]
    assert conclusion["remaining_before"] == pytest.approx(8)
    assert conclusion["actual_timeout"] == 8
    assert conclusion["actual_timeout"] <= conclusion["remaining_before"]
    result = router.build_recommendation({})
    assert result.description.startswith("Continue monitoring")
    assert groq.records[3]["remaining_before"] == pytest.approx(5)
    assert groq.records[3]["actual_timeout"] == 5


def test_conclusion_leaves_less_than_configured_timeout_but_recommendation_runs():
    groq = TimedLeaf(
        "groq",
        costs={"diagnose": 11, "build_conclusion": 5, "build_recommendation": 3},
        diagnose=_diagnosis(),
        build_conclusion=_conclusion(),
        build_recommendation=_recommendation(),
    )
    router = ProviderRouter([groq], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    router.diagnose({})
    assert groq.records[0]["remaining_before"] == pytest.approx(30)
    router.build_conclusion({})
    assert groq.records[1]["remaining_before"] == pytest.approx(19)
    assert groq.records[1]["actual_timeout"] == 15
    rec = router.build_recommendation({})
    assert rec.action_type == RecommendationAction.CONTINUE_MONITORING
    rec_record = groq.records[-1]
    assert rec_record["stage"] == "build_recommendation"
    assert rec_record["remaining_before"] == pytest.approx(14)
    assert rec_record["actual_timeout"] == 14
    assert rec_record["configured_timeout"] == 15
    metrics = (router.last_call_metrics or {}).get("attempts") or []
    assert metrics
    last = metrics[-1]
    assert last["actual_timeout_ms"] == 14000
    assert last["remaining_budget_before_ms"] == 14000
    assert last["configured_timeout_ms"] == 15000
    assert last["stage"] == "build_recommendation"
    assert router._remaining_seconds == pytest.approx(11)


def test_groq_timeout_with_remaining_budget_failsover_to_gemini():
    groq = TimedLeaf(
        "groq",
        costs={"diagnose": 8},
        diagnose=ProviderTimeoutError("timeout"),
    )
    gemini = TimedLeaf("gemini", diagnose=_diagnosis())
    openai = TimedLeaf("openai", diagnose=_diagnosis())
    router = ProviderRouter([groq, gemini, openai], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    result = router.diagnose({})
    assert groq.invocations == 1
    assert gemini.invocations == 1
    assert openai.invocations == 0
    assert result.reasoning_summary == "Insufficient evidence"
    assert gemini.records[0]["remaining_before"] == pytest.approx(22)
    assert gemini.records[0]["actual_timeout"] == 15
    assert gemini.records[0]["actual_timeout"] <= gemini.records[0]["remaining_before"]
    assert (router.last_call_metrics or {}).get("fallback_occurred") is True
    attempts = (router.last_call_metrics or {}).get("attempts") or []
    assert any(item.get("provider") == "gemini" and item.get("fallback") is True for item in attempts)


def test_groq_timeout_does_not_start_fresh_fifteen_second_gemini_window():
    groq = TimedLeaf(
        "groq",
        costs={"diagnose": 8},
        diagnose=ProviderTimeoutError("timeout"),
    )
    gemini = TimedLeaf("gemini", diagnose=_diagnosis())
    router = ProviderRouter([groq, gemini], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    router._remaining_seconds = 12
    result = router.diagnose({})
    assert groq.invocations == 1
    assert groq.records[0]["actual_timeout"] == 12
    assert gemini.invocations == 1
    assert gemini.records[0]["remaining_before"] == pytest.approx(4)
    assert gemini.records[0]["actual_timeout"] == 4
    assert gemini.records[0]["actual_timeout"] != 15
    assert result.confidence == ConfidenceLevel.LOW


def test_groq_timeout_with_insufficient_remaining_does_not_start_gemini():
    groq = TimedLeaf(
        "groq",
        costs={"diagnose": 15},
        diagnose=ProviderTimeoutError("timeout"),
    )
    gemini = TimedLeaf("gemini", diagnose=_diagnosis())
    router = ProviderRouter([groq, gemini], budget_seconds=16, timeout_seconds=15, max_leaf_attempts=1)
    with pytest.raises(ProviderTimeoutError):
        router.diagnose({})
    assert groq.invocations == 1
    assert gemini.invocations == 0
    attempts = (router.last_call_metrics or {}).get("attempts") or []
    assert any(item.get("failure_category") == "budget_too_small" for item in attempts)
    assert all(item.get("provider") != "gemini" or item.get("attempt") == 0 for item in attempts)


def test_cooldown_skips_groq_and_uses_gemini_when_budget_allows():
    groq = TimedLeaf("groq", diagnose=_diagnosis(summary="groq"))
    gemini = TimedLeaf("gemini", diagnose=_diagnosis(summary="gemini"))
    _mark_cooldown("groq")
    router = ProviderRouter([groq, gemini], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    router._remaining_seconds = 14
    result = router.diagnose({})
    assert groq.invocations == 0
    assert gemini.invocations == 1
    assert result.reasoning_summary == "gemini"
    assert gemini.records[0]["actual_timeout"] == 14
    attempts = (router.last_call_metrics or {}).get("attempts") or []
    assert any(item.get("cooldown_skipped") or item.get("failure_category") == "cooldown_skipped" for item in attempts)
    assert (router.last_call_metrics or {}).get("cooldown_skipped") is True


def test_recommendation_succeeds_with_reduced_remaining_timeout():
    groq = TimedLeaf("groq", build_recommendation=_recommendation())
    router = ProviderRouter([groq], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    router._remaining_seconds = 9
    result = router.build_recommendation({})
    assert result.human_validation_required is True
    assert groq.records[0]["actual_timeout"] == 9
    assert groq.records[0]["configured_timeout"] == 15
    record = ((router.last_call_metrics or {}).get("attempts") or [{}])[-1]
    assert record["actual_timeout_ms"] == 9000
    assert record["remaining_budget_before_ms"] == 9000
    assert record["stage"] == "build_recommendation"


def test_total_investigation_never_exceeds_hard_budget():
    groq = TimedLeaf("groq", costs={"diagnose": 15}, diagnose=ProviderTimeoutError("timeout"))
    gemini = TimedLeaf("gemini", costs={"diagnose": 15}, diagnose=ProviderTimeoutError("timeout"))
    openai = TimedLeaf("openai", costs={"diagnose": 15}, diagnose=ProviderTimeoutError("timeout"))
    router = ProviderRouter([groq, gemini, openai], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    with pytest.raises(ProviderTimeoutError):
        router.diagnose({})
    spent = 30 - router._remaining_seconds
    assert spent <= 30 + 1e-9
    assert groq.invocations == 1
    assert gemini.invocations == 1
    assert openai.invocations == 0
    assert groq.records[0]["actual_timeout"] == 15
    assert gemini.records[0]["actual_timeout"] == 15
    duration_ms = sum(int(item.get("duration_ms") or 0) for item in (router.last_call_metrics or {}).get("attempts") or [])
    assert duration_ms <= 30_000


def test_below_min_useful_remaining_is_a_clean_skip():
    groq = TimedLeaf("groq", diagnose=_diagnosis())
    gemini = TimedLeaf("gemini", diagnose=_diagnosis())
    router = ProviderRouter([groq, gemini], budget_seconds=30, timeout_seconds=15, max_leaf_attempts=1)
    router._remaining_seconds = 2
    with pytest.raises(ProviderTimeoutError, match="budget exceeded"):
        router.diagnose({})
    assert groq.invocations == 0
    assert gemini.invocations == 0
    attempts = (router.last_call_metrics or {}).get("attempts") or []
    assert any(item.get("failure_category") == "budget_too_small" for item in attempts)
    skipped = next(item for item in attempts if item.get("failure_category") == "budget_too_small")
    assert skipped["actual_timeout_ms"] == 0
    assert skipped["configured_timeout_ms"] == 15000
    assert skipped["remaining_budget_before_ms"] == 2000
    assert skipped["stage"] == "diagnose"
