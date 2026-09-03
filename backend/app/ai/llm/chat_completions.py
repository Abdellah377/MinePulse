"""OpenAI-compatible Chat Completions structured adapter (Groq, Gemini)."""

from __future__ import annotations

import json
import logging
import random
from time import monotonic
from typing import Any, TypeVar

from pydantic import BaseModel

from app.ai.contracts import (
    DiagnosisResult,
    InvestigationConclusion,
    InvestigationRecommendation,
    RecommendationDiscussionReply,
)
import app.ai.llm.provider as llm_provider
from app.ai.llm.provider import (
    _COMMON_POLICY,
    _CONCLUSION_PROMPT,
    _DIAGNOSIS_PROMPT,
    _DISCUSSION_PROMPT,
    _RECOMMENDATION_PROMPT,
    _TRANSIENT_PROVIDER_ERRORS,
    classify_provider_exception,
    commit_structured_attempt,
    budget_allows_attempt,
    LLMProviderError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from app.optimization.contracts import OptimizationPlannerDecision, OptimizationReview

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class ChatCompletionsLLMProvider:
    """Structured chat.completions adapter. Does not use OpenAI responses.parse."""

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 15,
        budget_seconds: float = 30,
        max_attempts: int = 2,
    ):
        if not api_key:
            raise ProviderConfigurationError(f"API key is required for provider {provider_name}")
        if not model:
            raise ProviderConfigurationError(f"Model is required for provider {provider_name}")
        if not base_url:
            raise ProviderConfigurationError(f"Base URL is required for provider {provider_name}")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderConfigurationError("The openai package is not installed") from exc
        self.provider_name = provider_name
        self.model_name = model
        self._timeout_seconds = timeout_seconds
        self._remaining_seconds = budget_seconds
        self._max_attempts = max(1, int(max_attempts))
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=0)
        self.last_call_metrics: dict | None = None
        self.last_attempt_count = 0

    def _structured(self, schema: type[_T], system_prompt: str, payload: dict) -> _T:
        last_error: LLMProviderError | None = None
        attempts = max(1, int(getattr(self, "_max_attempts", 1)))
        attempt_log: list[dict] = []
        for attempt in range(1, attempts + 1):
            self.last_attempt_count = attempt
            if not budget_allows_attempt(self._remaining_seconds, self._timeout_seconds):
                raise ProviderTimeoutError("Investigation provider budget exceeded")
            started = monotonic()
            response = None
            parsed: Any = None
            succeeded = False
            mapped_error: LLMProviderError | None = None
            try:
                parsed, response = self._parse_chat(schema, system_prompt, payload)
                succeeded = True
            except LLMProviderError as exc:
                mapped = exc
                logger.error(
                    "AI provider failure provider=%s model=%s schema=%s type=%s category=%s attempt=%s/%s",
                    self.provider_name,
                    self.model_name,
                    schema.__name__,
                    type(exc).__name__,
                    type(mapped).__name__,
                    attempt,
                    attempts,
                )
                last_error = mapped
                mapped_error = mapped
                retryable = isinstance(mapped, _TRANSIENT_PROVIDER_ERRORS) and attempt < attempts
                if isinstance(mapped, ProviderRateLimitError):
                    retryable = retryable and attempt == 1
                if not retryable:
                    raise mapped from exc
                delay = min(_retry_after_seconds(exc) or (min(2 ** (attempt - 1), 4) * (0.5 + random.random())), 2.0)
                logger.info(
                    "Retrying transient AI provider failure provider=%s category=%s attempt=%s delay_s=%.2f",
                    self.provider_name,
                    type(mapped).__name__,
                    attempt,
                    delay,
                )
                llm_provider._sleep(delay)
            except Exception as exc:
                mapped = classify_provider_exception(exc)
                logger.error(
                    "AI provider failure provider=%s model=%s schema=%s type=%s category=%s status=%s request_id=%s attempt=%s/%s",
                    self.provider_name,
                    self.model_name,
                    schema.__name__,
                    type(exc).__name__,
                    type(mapped).__name__,
                    getattr(exc, "status_code", None),
                    getattr(exc, "request_id", None),
                    attempt,
                    attempts,
                )
                last_error = mapped
                mapped_error = mapped
                retryable = isinstance(mapped, _TRANSIENT_PROVIDER_ERRORS) and attempt < attempts
                if isinstance(mapped, ProviderRateLimitError):
                    retryable = retryable and attempt == 1
                if not retryable:
                    raise mapped from exc
                delay = min(_retry_after_seconds(exc) or (min(2 ** (attempt - 1), 4) * (0.5 + random.random())), 2.0)
                logger.info(
                    "Retrying transient AI provider failure provider=%s category=%s attempt=%s delay_s=%.2f",
                    self.provider_name,
                    type(mapped).__name__,
                    attempt,
                    delay,
                )
                llm_provider._sleep(delay)
            finally:
                elapsed = monotonic() - started
                self._remaining_seconds -= elapsed
                usage = getattr(response, "usage", None) if response is not None else None
                metrics = commit_structured_attempt(
                    attempt_log,
                    provider_name=self.provider_name,
                    model_name=self.model_name,
                    schema_name=schema.__name__,
                    attempt=attempt,
                    started=started,
                    remaining_seconds=self._remaining_seconds,
                    payload=payload,
                    exc=mapped_error,
                    ok=succeeded,
                )
                metrics.update(
                    {
                        "input_tokens": getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None),
                        "total_tokens": getattr(usage, "total_tokens", None),
                    }
                )
                self.last_call_metrics = metrics
            if succeeded:
                return parsed
        raise last_error or LLMProviderError("AI provider structured response failed")

    def _parse_chat(self, schema: type[_T], system_prompt: str, payload: dict) -> tuple[_T, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        timeout = self._timeout_seconds
        parse = getattr(getattr(self._client.chat, "completions", None), "parse", None)
        if callable(parse):
            response = parse(
                model=self.model_name,
                messages=messages,
                response_format=schema,
                timeout=timeout,
            )
            parsed = None
            choices = getattr(response, "choices", None) or []
            if choices:
                parsed = getattr(getattr(choices[0], "message", None), "parsed", None)
            if parsed is None:
                raise ProviderResponseError(f"{self.provider_name} returned no structured output")
            try:
                return schema.model_validate(parsed), response
            except Exception as exc:
                raise ProviderResponseError(f"{self.provider_name} output failed {schema.__name__} validation") from exc

        from openai.lib._pydantic import to_strict_json_schema

        schema_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in schema.__name__)[:64]
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name or "MinePulseContract",
                    "schema": to_strict_json_schema(schema),
                    "strict": True,
                },
            },
            timeout=timeout,
        )
        content = None
        choices = getattr(response, "choices", None) or []
        if choices:
            content = getattr(getattr(choices[0], "message", None), "content", None)
        if not content:
            raise ProviderResponseError(f"{self.provider_name} returned no structured output")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"{self.provider_name} returned malformed JSON") from exc
        try:
            return schema.model_validate(data), response
        except Exception as exc:
            raise ProviderResponseError(f"{self.provider_name} output failed {schema.__name__} validation") from exc

    def diagnose(self, payload: dict) -> DiagnosisResult:
        return self._structured(DiagnosisResult, _DIAGNOSIS_PROMPT, payload)

    def build_conclusion(self, payload: dict) -> InvestigationConclusion:
        return self._structured(InvestigationConclusion, _CONCLUSION_PROMPT, payload)

    def build_recommendation(self, payload: dict) -> InvestigationRecommendation:
        return self._structured(InvestigationRecommendation, _RECOMMENDATION_PROMPT, payload)

    def discuss_recommendation(self, payload: dict) -> RecommendationDiscussionReply:
        return self._structured(RecommendationDiscussionReply, _DISCUSSION_PROMPT, payload)

    def plan_optimization(self, payload: dict) -> OptimizationPlannerDecision:
        from app.ai.optimization.prompts import PLANNER_BODY

        return self._structured(OptimizationPlannerDecision, _COMMON_POLICY + "\n\n" + PLANNER_BODY, payload)

    def review_optimization(self, payload: dict) -> OptimizationReview:
        from app.ai.optimization.prompts import REVIEWER_BODY

        return self._structured(OptimizationReview, _COMMON_POLICY + "\n\n" + REVIEWER_BODY, payload)


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None
