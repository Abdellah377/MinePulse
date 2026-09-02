from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.ai.contracts import ConfidenceLevel
from app.ai.contracts import DiagnosisResult
from app.ai.llm.provider import OpenAILLMProvider, ProviderConfigurationError, create_llm_provider


def test_provider_fails_clearly_when_not_configured():
    settings = SimpleNamespace(ai_provider=None, ai_model=None, openai_api_key=None)
    with pytest.raises(ProviderConfigurationError, match="No AI provider configured"):
        create_llm_provider(settings)


def test_openai_boundary_validates_structured_output_without_network():
    raw = {
        "hypotheses": [],
        "requested_information": [],
        "contradictions": [],
        "can_conclude": False,
        "confidence": "LOW",
        "confidence_rationale": "No production evidence is available.",
        "reasoning_summary": "Evidence is insufficient.",
    }
    provider = OpenAILLMProvider.__new__(OpenAILLMProvider)
    provider.model_name = "test-model"
    provider._remaining_seconds = 150
    provider._timeout_seconds = 45
    provider._client = SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **kwargs: SimpleNamespace(output_parsed=raw))
    )

    result = provider.diagnose({"evidence": []})

    assert result.confidence == ConfidenceLevel.LOW
    assert result.can_conclude is False


def test_diagnosis_schema_can_be_converted_to_openai_strict_schema():
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(DiagnosisResult)

    assert schema["additionalProperties"] is False
    assert "reasoning_summary" in schema["required"]


def test_provider_disables_retries_and_bounds_each_call(monkeypatch):
    import openai
    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(openai, "OpenAI", factory)
    provider = OpenAILLMProvider(api_key="test-only", model="test-model", timeout_seconds=30, budget_seconds=10)
    factory.assert_called_once_with(api_key="test-only", timeout=30, max_retries=0)
    client.responses.parse.return_value.output_parsed = DiagnosisResult(
        can_conclude=False, confidence="LOW", confidence_rationale="Unknown", reasoning_summary="Insufficient evidence")
    provider.diagnose({})
    assert client.responses.parse.call_args.kwargs["timeout"] == 10
    provider._remaining_seconds = 0
    from app.ai.llm.provider import ProviderTimeoutError
    with pytest.raises(ProviderTimeoutError):
        provider.diagnose({})
    assert client.responses.parse.call_count == 1


@pytest.mark.parametrize("kind,expected", [
    ("timeout", "ProviderTimeoutError"),
    ("auth", "ProviderAuthenticationError"),
    ("model", "ProviderModelError"),
    ("rate", "ProviderRateLimitError"),
    ("unavailable", "ProviderUnavailableError"),
])
def test_provider_errors_are_classified_without_exposing_sdk_bodies(monkeypatch, caplog, kind, expected):
    import openai
    import httpx
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(400, request=request)
    errors = {
        "timeout": openai.APITimeoutError(request=request),
        "auth": openai.AuthenticationError("secret-body", response=response, body=None),
        "model": openai.NotFoundError("secret-body", response=response, body=None),
        "rate": openai.RateLimitError("secret-body", response=httpx.Response(429, request=request), body=None),
        "unavailable": openai.InternalServerError("secret-body", response=httpx.Response(500, request=request), body=None),
    }
    client = MagicMock()
    client.responses.parse.side_effect = errors[kind]
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    monkeypatch.setattr("app.ai.llm.provider._sleep", lambda *_: None)
    provider = OpenAILLMProvider(api_key="test-only", model="test-model", max_attempts=1)
    with pytest.raises(Exception) as caught:
        provider.diagnose({})
    assert type(caught.value).__name__ == expected
    assert "secret-body" not in str(caught.value)
    assert "secret-body" not in caplog.text
    assert client.responses.parse.call_count == 1


def test_transient_provider_errors_retry_with_a_bounded_budget(monkeypatch):
    import openai
    import httpx
    from app.ai.contracts import ConfidenceLevel, DiagnosisResult

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    rate = openai.RateLimitError("secret-body", response=httpx.Response(429, request=request), body=None)
    parsed = DiagnosisResult(
        can_conclude=False, confidence=ConfidenceLevel.LOW,
        confidence_rationale="Unknown", reasoning_summary="Insufficient evidence",
    )
    client = MagicMock()
    client.responses.parse.side_effect = [rate, rate, SimpleNamespace(output_parsed=parsed)]
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    sleeps = []
    monkeypatch.setattr("app.ai.llm.provider._sleep", lambda delay: sleeps.append(delay))
    provider = OpenAILLMProvider(api_key="test-only", model="test-model", max_attempts=3, budget_seconds=30)
    result = provider.diagnose({})
    assert result.confidence == ConfidenceLevel.LOW
    assert client.responses.parse.call_count == 3
    assert len(sleeps) == 2
    assert provider.last_attempt_count == 3
    assert all(delay > 0 for delay in sleeps)


def test_auth_errors_are_not_retried(monkeypatch):
    import openai
    import httpx
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    auth = openai.AuthenticationError("secret-body", response=httpx.Response(401, request=request), body=None)
    client = MagicMock()
    client.responses.parse.side_effect = auth
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
    monkeypatch.setattr("app.ai.llm.provider._sleep", lambda *_: (_ for _ in ()).throw(AssertionError("slept")))
    provider = OpenAILLMProvider(api_key="test-only", model="test-model", max_attempts=3)
    with pytest.raises(Exception) as caught:
        provider.diagnose({})
    assert type(caught.value).__name__ == "ProviderAuthenticationError"
    assert client.responses.parse.call_count == 1
