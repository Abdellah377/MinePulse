from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ai.contracts import ConfidenceLevel, DiagnosisResult
from app.ai.llm.chat_completions import ChatCompletionsLLMProvider
from app.ai.llm.provider import (
    LLMProviderError,
    OpenAILLMProvider,
    ProviderConfigurationError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    create_llm_provider,
)
from app.ai.llm.router import ProviderRouter, clear_provider_cooldowns
from app.optimization.contracts import OptimizationPlannerDecision, OptimizationReview, OptimizerId, ProblemType, ReviewStatus


@pytest.fixture(autouse=True)
def _reset_cooldowns():
    clear_provider_cooldowns()
    yield
    clear_provider_cooldowns()


def _settings(**overrides):
    values = dict(
        ai_provider=None,
        ai_provider_order=None,
        ai_model=None,
        openai_api_key=None,
        openai_model=None,
        groq_api_key=None,
        groq_model=None,
        groq_base_url="https://api.groq.com/openai/v1",
        gemini_api_key=None,
        gemini_model=None,
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        ai_provider_timeout_seconds=45,
        ai_investigation_llm_budget_seconds=150,
        ai_provider_max_attempts=3,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _diagnosis(**kwargs):
    return DiagnosisResult(
        can_conclude=False,
        confidence=ConfidenceLevel.LOW,
        confidence_rationale=kwargs.get("rationale", "Unknown"),
        reasoning_summary=kwargs.get("summary", "Insufficient evidence"),
    )


def _planner():
    return OptimizationPlannerDecision(
        selected_optimizers=[OptimizerId.DISPATCH_LOADER],
        problem_type=ProblemType.CONGESTION_RISK,
    )


def _review():
    return OptimizationReview(status=ReviewStatus.APPROVED)


class FakeLeaf:
    def __init__(self, name, *, model="test-model", attempts=1, **handlers):
        self.provider_name = name
        self.model_name = model
        self._remaining_seconds = 150
        self._max_attempts = 2
        self.last_attempt_count = 0
        self.last_call_metrics = None
        self.calls: list[tuple[str, dict]] = []
        self._handlers = handlers
        self._attempts = attempts
        self.invocations = 0

    def _run(self, method: str, payload: dict):
        self.invocations += 1
        self.calls.append((method, payload))
        self.last_attempt_count = self._attempts
        self.last_call_metrics = {"provider": self.provider_name, "model": self.model_name, "schema": method}
        spec = self._handlers.get(method, self._handlers.get("*"))
        if callable(spec) and not isinstance(spec, Exception):
            spec = spec()
        if isinstance(spec, Exception):
            raise spec
        if spec is None:
            raise ProviderUnavailableError(f"{self.provider_name} has no handler")
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


def _router(*leaves, budget=150):
    return ProviderRouter(list(leaves), budget_seconds=budget, timeout_seconds=45, max_leaf_attempts=2)


def test_groq_success_does_not_call_fallbacks():
    groq = FakeLeaf("groq", diagnose=_diagnosis())
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    openai = FakeLeaf("openai", diagnose=_diagnosis())
    result = _router(groq, gemini, openai).diagnose({"k": 1})
    assert result.confidence == ConfidenceLevel.LOW
    assert groq.invocations == 1
    assert gemini.invocations == 0
    assert openai.invocations == 0
    assert groq.calls[0][1] == {"k": 1}


def test_groq_timeout_failsover_to_gemini():
    payload = {"same": True}
    groq = FakeLeaf("groq", diagnose=ProviderTimeoutError("timeout"), attempts=2)
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    openai = FakeLeaf("openai", diagnose=_diagnosis())
    router = _router(groq, gemini, openai)
    result = router.diagnose(payload)
    assert gemini.invocations == 1
    assert openai.invocations == 0
    assert gemini.calls[0][1] is payload
    assert router.last_call_metrics["final_provider"] == "gemini"
    assert router.last_call_metrics["fallback_occurred"] is True


def test_groq_429_failsover_to_gemini():
    groq = FakeLeaf("groq", diagnose=ProviderRateLimitError("rate"), attempts=1)
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    result = _router(groq, gemini, FakeLeaf("openai", diagnose=_diagnosis())).diagnose({})
    assert gemini.invocations == 1
    assert groq.invocations == 1


def test_groq_5xx_failsover_to_gemini():
    groq = FakeLeaf("groq", diagnose=ProviderUnavailableError("5xx"))
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    _router(groq, gemini).diagnose({})
    assert gemini.invocations == 1


def test_groq_and_gemini_fail_openai_succeeds():
    groq = FakeLeaf("groq", diagnose=ProviderTimeoutError("t"))
    gemini = FakeLeaf("gemini", diagnose=ProviderUnavailableError("5xx"))
    openai = FakeLeaf("openai", diagnose=_diagnosis(summary="openai"))
    result = _router(groq, gemini, openai).diagnose({})
    assert result.reasoning_summary == "openai"
    assert openai.invocations == 1


def test_all_fail_raises_stable_provider_error():
    groq = FakeLeaf("groq", diagnose=ProviderTimeoutError("t"))
    gemini = FakeLeaf("gemini", diagnose=ProviderUnavailableError("5xx"))
    openai = FakeLeaf("openai", diagnose=ProviderNetworkError("n"))
    with pytest.raises(LLMProviderError) as caught:
        _router(groq, gemini, openai).diagnose({})
    assert type(caught.value).__name__ == "ProviderNetworkError"


def test_valid_structured_result_does_not_failover():
    groq = FakeLeaf("groq", diagnose=_diagnosis(rationale="low but valid"))
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    _router(groq, gemini).diagnose({})
    assert gemini.invocations == 0


def test_malformed_json_failsover_or_errors(monkeypatch):
    groq = FakeLeaf("groq", diagnose=ProviderResponseError("malformed JSON"))
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    result = _router(groq, gemini).diagnose({})
    assert gemini.invocations == 1
    assert result.can_conclude is False

    last = FakeLeaf("groq", diagnose=ProviderResponseError("malformed JSON"))
    with pytest.raises(ProviderResponseError):
        _router(last).diagnose({})


def test_chat_adapter_malformed_json_is_response_error():
    leaf = ChatCompletionsLLMProvider.__new__(ChatCompletionsLLMProvider)
    leaf.provider_name = "groq"
    leaf.model_name = "test-model"
    leaf._timeout_seconds = 45
    leaf._remaining_seconds = 30
    leaf._max_attempts = 1
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{not-json", parsed=None))],
        usage=None,
    )
    leaf._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=None, create=lambda **_k: response)))
    with pytest.raises(ProviderResponseError, match="malformed JSON"):
        leaf.diagnose({"evidence": []})


def test_missing_optional_key_is_skipped(monkeypatch):
    import openai

    monkeypatch.setattr(openai, "OpenAI", MagicMock())
    router = create_llm_provider(
        _settings(
            ai_provider_order="groq,openai",
            openai_api_key="test-only",
            openai_model="test-model",
        )
    )
    assert [leaf.provider_name for leaf in router._providers] == ["openai"]


def test_no_providers_raises_configuration_error():
    with pytest.raises(ProviderConfigurationError, match="No AI provider configured"):
        create_llm_provider(_settings())


def test_provider_order_is_respected(monkeypatch):
    import openai

    created = []

    def factory(**kwargs):
        created.append(kwargs.get("base_url"))
        return MagicMock()

    monkeypatch.setattr(openai, "OpenAI", factory)
    router = create_llm_provider(
        _settings(
            ai_provider="openai",
            ai_provider_order="gemini,groq,openai",
            groq_api_key="gsk_test",
            groq_model="openai/gpt-oss-120b",
            gemini_api_key="AIza-test",
            gemini_model="gemini-test",
            openai_api_key="sk-test",
            openai_model="gpt-test",
        )
    )
    assert [leaf.provider_name for leaf in router._providers] == ["gemini", "groq", "openai"]


def test_same_payload_object_passed_on_failover_and_review():
    planner_payload = {"facts": {"alertType": "CONGESTION_RISK"}}
    reviewer_payload = {"planner": {"selected_optimizers": ["DISPATCH_LOADER"]}, "candidates": []}
    groq = FakeLeaf(
        "groq",
        plan_optimization=_planner(),
        review_optimization=ProviderTimeoutError("timeout"),
    )
    gemini = FakeLeaf("gemini", review_optimization=_review())
    router = _router(groq, gemini)
    assert router.plan_optimization(planner_payload).selected_optimizers
    assert groq.calls[0][1] is planner_payload
    review = router.review_optimization(reviewer_payload)
    assert review.status == ReviewStatus.APPROVED
    assert gemini.calls[0][1] is reviewer_payload
    assert gemini.calls[0][1]["planner"] is reviewer_payload["planner"]


def test_logs_never_include_provider_keys(caplog, monkeypatch):
    groq = FakeLeaf("groq", diagnose=ProviderTimeoutError("timeout"))
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    with caplog.at_level("ERROR"):
        _router(groq, gemini).diagnose({"api_key": "should-not-matter"})
    text = caplog.text
    assert "sk-" not in text
    assert "gsk_" not in text
    assert "AIza" not in text


def test_attempt_count_is_bounded():
    groq = FakeLeaf("groq", diagnose=ProviderTimeoutError("t"), attempts=2)
    gemini = FakeLeaf("gemini", diagnose=ProviderUnavailableError("5xx"), attempts=2)
    openai = FakeLeaf("openai", diagnose=ProviderNetworkError("n"), attempts=2)
    router = _router(groq, gemini, openai)
    with pytest.raises(LLMProviderError):
        router.diagnose({})
    assert groq.invocations == gemini.invocations == openai.invocations == 1
    assert router.last_attempt_count <= 6


def test_429_cooldown_skips_groq_on_the_next_logical_call():
    groq = FakeLeaf("groq", diagnose=ProviderRateLimitError("rate"))
    gemini = FakeLeaf("gemini", diagnose=_diagnosis())
    router = _router(groq, gemini)
    router.diagnose({})
    router.diagnose({})
    assert groq.invocations == 1
    assert gemini.invocations == 2


def test_unsupported_single_provider_is_configuration_error():
    with pytest.raises(ProviderConfigurationError, match="Unsupported AI_PROVIDER"):
        create_llm_provider(_settings(ai_provider="not-a-vendor"))


def test_create_llm_provider_returns_router_for_openai_only(monkeypatch):
    import openai

    monkeypatch.setattr(openai, "OpenAI", MagicMock())
    router = create_llm_provider(_settings(ai_provider="openai", openai_api_key="test-only", ai_model="test-model"))
    assert isinstance(router, ProviderRouter)
    assert router.provider_name == "openai"
    assert isinstance(router._providers[0], OpenAILLMProvider)
