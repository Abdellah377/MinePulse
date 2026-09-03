"""MinePulse-owned LLM provider router with technical-only failover."""

from __future__ import annotations

import logging
import threading
from time import monotonic
from typing import Any, Callable

from app.ai.contracts import (
    DiagnosisResult,
    InvestigationConclusion,
    InvestigationRecommendation,
    RecommendationDiscussionReply,
)
from app.ai.llm.chat_completions import (
    GEMINI_DEFAULT_BASE_URL,
    GROQ_DEFAULT_BASE_URL,
    ChatCompletionsLLMProvider,
)
from app.ai.llm.openai_responses import OpenAILLMProvider
from app.ai.llm.provider import (
    LLMProviderError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.config import Settings
from app.optimization.contracts import OptimizationPlannerDecision, OptimizationReview

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("groq", "gemini", "openai")
RATE_LIMIT_COOLDOWN_SECONDS = 30.0

_cooldown_until: dict[str, float] = {}
_cooldown_lock = threading.Lock()


def clear_provider_cooldowns() -> None:
    with _cooldown_lock:
        _cooldown_until.clear()


def _in_cooldown(name: str) -> bool:
    with _cooldown_lock:
        until = _cooldown_until.get(name, 0.0)
        return monotonic() < until


def _mark_cooldown(name: str, seconds: float = RATE_LIMIT_COOLDOWN_SECONDS) -> None:
    with _cooldown_lock:
        _cooldown_until[name] = monotonic() + seconds


def parse_provider_order(settings: Settings | Any) -> list[str]:
    raw_order = str(getattr(settings, "ai_provider_order", None) or "").strip()
    if raw_order:
        return [part.strip().lower() for part in raw_order.split(",") if part.strip()]
    single = str(getattr(settings, "ai_provider", None) or "").strip().lower()
    return [single] if single else []


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _build_leaf(
    name: str,
    settings: Settings | Any,
    *,
    timeout_seconds: float,
    budget_seconds: float,
    max_attempts: int,
    required: bool,
) -> Any | None:
    if name not in SUPPORTED_PROVIDERS:
        if required:
            raise ProviderConfigurationError(f"Unsupported AI_PROVIDER: {name}")
        logger.info("Skipping unknown AI provider name=%s", name)
        return None

    if name == "openai":
        api_key = _optional_text(getattr(settings, "openai_api_key", None))
        model = _optional_text(getattr(settings, "openai_model", None)) or _optional_text(
            getattr(settings, "ai_model", None)
        )
        if not api_key or not model:
            if required:
                return OpenAILLMProvider(
                    api_key=api_key,
                    model=model,
                    timeout_seconds=timeout_seconds,
                    budget_seconds=budget_seconds,
                    max_attempts=max_attempts,
                )
            logger.info("Skipping unconfigured AI provider name=%s", name)
            return None
        return OpenAILLMProvider(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            budget_seconds=budget_seconds,
            max_attempts=max_attempts,
        )

    if name == "groq":
        api_key = _optional_text(getattr(settings, "groq_api_key", None))
        model = _optional_text(getattr(settings, "groq_model", None))
        base_url = _optional_text(getattr(settings, "groq_base_url", None)) or GROQ_DEFAULT_BASE_URL
        if not api_key or not model:
            if required:
                raise ProviderConfigurationError("GROQ_API_KEY and GROQ_MODEL are required when AI_PROVIDER=groq")
            logger.info("Skipping unconfigured AI provider name=%s", name)
            return None
        return ChatCompletionsLLMProvider(
            provider_name="groq",
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            budget_seconds=budget_seconds,
            max_attempts=max_attempts,
        )

    api_key = _optional_text(getattr(settings, "gemini_api_key", None))
    model = _optional_text(getattr(settings, "gemini_model", None))
    base_url = _optional_text(getattr(settings, "gemini_base_url", None)) or GEMINI_DEFAULT_BASE_URL
    if not api_key or not model:
        if required:
            raise ProviderConfigurationError("GEMINI_API_KEY and GEMINI_MODEL are required when AI_PROVIDER=gemini")
        logger.info("Skipping unconfigured AI provider name=%s", name)
        return None
    return ChatCompletionsLLMProvider(
        provider_name="gemini",
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        budget_seconds=budget_seconds,
        max_attempts=max_attempts,
    )


class ProviderRouter:
    """Walks configured leaves with a shared budget. Failover is technical-only."""

    def __init__(
        self,
        providers: list[Any],
        *,
        budget_seconds: float,
        timeout_seconds: float,
        max_leaf_attempts: int,
    ):
        if not providers:
            raise ProviderConfigurationError(
                "No AI provider configured. Set AI_PROVIDER_ORDER or AI_PROVIDER with the matching API key and model."
            )
        self._providers = list(providers)
        self._remaining_seconds = float(budget_seconds)
        self._timeout_seconds = float(timeout_seconds)
        self._max_leaf_attempts = max(1, int(max_leaf_attempts))
        self.provider_name = self._providers[0].provider_name
        self.model_name = self._providers[0].model_name
        self.last_call_metrics: dict | None = None
        self.last_attempt_count = 0

    def _sync_budget(self, leaf: Any) -> None:
        remaining = float(getattr(leaf, "_remaining_seconds", self._remaining_seconds))
        self._remaining_seconds = remaining
        for other in self._providers:
            other._remaining_seconds = remaining

    def _record_success(self, leaf: Any, *, fallback_occurred: bool, http_attempts: int) -> None:
        metrics = dict(getattr(leaf, "last_call_metrics", None) or {})
        metrics.update(
            {
                "provider": leaf.provider_name,
                "model": getattr(leaf, "model_name", metrics.get("model")),
                "fallback_occurred": fallback_occurred,
                "configured_providers": [item.provider_name for item in self._providers],
                "final_provider": leaf.provider_name,
                "attempt": http_attempts,
            }
        )
        self.last_call_metrics = metrics
        self.last_attempt_count = http_attempts
        leaf.last_call_metrics = metrics

    def _invoke(self, method: str, payload: dict) -> Any:
        last_error: LLMProviderError | None = None
        http_attempts = 0
        cap = len(self._providers) * 2
        attempted_index: int | None = None
        for index, leaf in enumerate(self._providers):
            if _in_cooldown(leaf.provider_name):
                logger.info("Skipping AI provider in cooldown provider=%s", leaf.provider_name)
                continue
            if self._remaining_seconds <= 0:
                raise last_error or ProviderTimeoutError("Investigation provider budget exceeded")
            remaining_slots = cap - http_attempts
            if remaining_slots <= 0:
                break
            leaf._max_attempts = min(self._max_leaf_attempts, remaining_slots)
            leaf._remaining_seconds = self._remaining_seconds
            attempted_index = index
            call: Callable[[dict], Any] = getattr(leaf, method)
            try:
                result = call(payload)
            except LLMProviderError as exc:
                self._sync_budget(leaf)
                used = max(1, int(getattr(leaf, "last_attempt_count", 1) or 1))
                http_attempts += used
                self.last_attempt_count = http_attempts
                last_error = exc
                logger.error(
                    "AI provider failover candidate failed provider=%s category=%s attempt_total=%s/%s",
                    leaf.provider_name,
                    type(exc).__name__,
                    http_attempts,
                    cap,
                )
                if isinstance(exc, ProviderRateLimitError):
                    _mark_cooldown(leaf.provider_name)
                if isinstance(exc, ProviderTimeoutError) and self._remaining_seconds <= 0:
                    self.last_call_metrics = dict(getattr(leaf, "last_call_metrics", None) or {})
                    self.last_call_metrics.update(
                        {
                            "provider": leaf.provider_name,
                            "fallback_occurred": index > 0,
                            "configured_providers": [item.provider_name for item in self._providers],
                            "final_provider": leaf.provider_name,
                        }
                    )
                    raise
                continue
            except Exception as exc:
                mapped = exc if isinstance(exc, LLMProviderError) else LLMProviderError("AI provider structured response failed")
                self._sync_budget(leaf)
                used = max(1, int(getattr(leaf, "last_attempt_count", 1) or 1))
                http_attempts += used
                last_error = mapped
                continue
            self._sync_budget(leaf)
            used = max(1, int(getattr(leaf, "last_attempt_count", 1) or 1))
            http_attempts += used
            self._record_success(
                leaf,
                fallback_occurred=index > 0 or attempted_index != 0,
                http_attempts=http_attempts,
            )
            return result
        raise last_error or ProviderUnavailableError("AI providers unavailable")

    def diagnose(self, payload: dict) -> DiagnosisResult:
        return self._invoke("diagnose", payload)

    def build_conclusion(self, payload: dict) -> InvestigationConclusion:
        return self._invoke("build_conclusion", payload)

    def build_recommendation(self, payload: dict) -> InvestigationRecommendation:
        return self._invoke("build_recommendation", payload)

    def discuss_recommendation(self, payload: dict) -> RecommendationDiscussionReply:
        return self._invoke("discuss_recommendation", payload)

    def plan_optimization(self, payload: dict) -> OptimizationPlannerDecision:
        return self._invoke("plan_optimization", payload)

    def review_optimization(self, payload: dict) -> OptimizationReview:
        return self._invoke("review_optimization", payload)


def build_provider_router(settings: Settings | Any) -> ProviderRouter:
    order = parse_provider_order(settings)
    explicit_order = bool(str(getattr(settings, "ai_provider_order", None) or "").strip())
    if not order:
        raise ProviderConfigurationError(
            "No AI provider configured. Set AI_PROVIDER=openai, AI_MODEL, and OPENAI_API_KEY."
        )

    timeout_seconds = float(getattr(settings, "ai_provider_timeout_seconds", 45) or 45)
    budget_seconds = float(getattr(settings, "ai_investigation_llm_budget_seconds", 150) or 150)
    configured_attempts = int(getattr(settings, "ai_provider_max_attempts", 3) or 3)
    multi = explicit_order or len(order) > 1
    max_leaf_attempts = min(configured_attempts, 2) if multi else configured_attempts

    leaves: list[Any] = []
    for name in order:
        leaf = _build_leaf(
            name,
            settings,
            timeout_seconds=timeout_seconds,
            budget_seconds=budget_seconds,
            max_attempts=max_leaf_attempts,
            required=not explicit_order and len(order) == 1,
        )
        if leaf is not None:
            leaves.append(leaf)

    if not leaves:
        raise ProviderConfigurationError(
            "No AI provider configured. Set AI_PROVIDER_ORDER or AI_PROVIDER with the matching API key and model."
        )
    return ProviderRouter(
        leaves,
        budget_seconds=budget_seconds,
        timeout_seconds=timeout_seconds,
        max_leaf_attempts=max_leaf_attempts,
    )
