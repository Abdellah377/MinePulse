"""OpenAI Responses API implementation with native Pydantic parsing."""

from __future__ import annotations

import json
import logging
import random
from time import monotonic
from typing import TypeVar

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


class OpenAILLMProvider:
    """OpenAI Responses API implementation with native Pydantic parsing."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 15,
        budget_seconds: float = 30,
        max_attempts: int = 2,
    ):
        if not api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        if not model:
            raise ProviderConfigurationError("AI_MODEL is required when AI_PROVIDER=openai")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - exercised only in incomplete deployments
            raise ProviderConfigurationError("The openai package is not installed") from exc
        self.model_name = model
        self._timeout_seconds = timeout_seconds
        self._remaining_seconds = budget_seconds
        self._max_attempts = max(1, int(max_attempts))
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)
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
            parsed = None
            succeeded = False
            mapped_error: LLMProviderError | None = None
            try:
                response = self._client.responses.parse(
                    model=self.model_name,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    text_format=schema,
                    store=False,
                    timeout=self._timeout_seconds,
                )
                parsed = response.output_parsed
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
                if not retryable:
                    raise mapped from exc
                delay = min(2 ** (attempt - 1), 4) * (0.5 + random.random())
                if isinstance(mapped, ProviderRateLimitError):
                    delay = min(_retry_after_seconds(exc) or delay, 2.0)
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
                    ok=succeeded or parsed is not None,
                )
                metrics.update(
                    {
                        "input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None),
                        "total_tokens": getattr(usage, "total_tokens", None),
                    }
                )
                self.last_call_metrics = metrics
            if parsed is None and mapped_error is None:
                raise ProviderResponseError("OpenAI returned no structured output")
            if parsed is None:
                continue
            try:
                return schema.model_validate(parsed)
            except Exception as exc:
                raise ProviderResponseError(f"OpenAI output failed {schema.__name__} validation") from exc
        raise last_error or LLMProviderError("AI provider structured response failed")

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
