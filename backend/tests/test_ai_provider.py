from types import SimpleNamespace

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
