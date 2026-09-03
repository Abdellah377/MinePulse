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
    budget_allows_attempt,
    http_status_class_for,
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

    def _admission_record(
        self,
        leaf: Any,
        *,
        method: str,
        failure_category: str,
        http_status_class: str,
        cooldown_skipped: bool = False,
        fallback: bool = False,
    ) -> dict[str, Any]:
        remaining_ms = int(max(0.0, self._remaining_seconds) * 1000)
        return {
            "provider": leaf.provider_name,
            "model": getattr(leaf, "model_name", None),
            "attempt": 0,
            "stage": method,
            "duration_ms": 0,
            "http_status_class": http_status_class,
            "failure_category": failure_category,
            "parse_retry": False,
            "prompt_chars": 0,
            "evidence_count": 0,
            "configured_timeout_ms": int(max(0.0, self._timeout_seconds) * 1000),
            "actual_timeout_ms": 0,
            "remaining_budget_before_ms": remaining_ms,
            "remaining_budget_after_ms": remaining_ms,
            "remaining_budget_ms": remaining_ms,
            "fallback": fallback,
            "cooldown_skipped": cooldown_skipped,
        }

    def _stamp_attempts(self, attempts: list[dict[str, Any]], *, method: str, fallback: bool) -> list[dict[str, Any]]:
        for item in attempts:
            item.setdefault("stage", method)
            item.setdefault("configured_timeout_ms", int(max(0.0, self._timeout_seconds) * 1000))
            item.setdefault("actual_timeout_ms", 0)
            item.setdefault("remaining_budget_before_ms", item.get("remaining_budget_ms") or 0)
            item.setdefault("remaining_budget_after_ms", item.get("remaining_budget_ms") or 0)
            item["fallback"] = fallback
            item.setdefault("cooldown_skipped", False)
        return attempts

    def _leaf_attempts(self, leaf: Any, exc: Exception | None = None) -> list[dict[str, Any]]:
        metrics = dict(getattr(leaf, "last_call_metrics", None) or {})
        raw = metrics.get("attempts")
        if isinstance(raw, list) and raw:
            attempts = [dict(item) for item in raw if isinstance(item, dict)]
        else:
            attempts = [
                {
                    "provider": leaf.provider_name,
                    "model": getattr(leaf, "model_name", metrics.get("model")),
                    "attempt": metrics.get("attempt") or getattr(leaf, "last_attempt_count", 1) or 1,
                    "duration_ms": int(metrics.get("duration_ms") or 0),
                    "http_status_class": "ok" if exc is None else http_status_class_for(exc),
                    "failure_category": None if exc is None else type(exc).__name__,
                    "parse_retry": False,
                    "prompt_chars": metrics.get("prompt_chars") or 0,
                    "evidence_count": metrics.get("evidence_count") or 0,
                    "remaining_budget_ms": int(self._remaining_seconds * 1000),
                }
            ]
        if exc is not None:
            klass = http_status_class_for(exc)
            category = type(exc).__name__
            for item in attempts:
                if item.get("http_status_class") in (None, "ok") and item.get("failure_category") is None:
                    item["http_status_class"] = klass
                    item["failure_category"] = category
        return attempts

    def _metrics_from_attempts(
        self,
        attempts: list[dict[str, Any]],
        *,
        leaf: Any,
        fallback_occurred: bool,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metrics = dict(getattr(leaf, "last_call_metrics", None) or {})
        metrics.update(
            {
                "provider": leaf.provider_name,
                "model": getattr(leaf, "model_name", metrics.get("model")),
                "fallback_occurred": fallback_occurred,
                "configured_providers": [item.provider_name for item in self._providers],
                "final_provider": leaf.provider_name,
                "attempt": len(attempts),
                "attempts": attempts,
                "duration_ms": sum(int(item.get("duration_ms") or 0) for item in attempts),
                "remaining_budget_ms": int(max(0.0, self._remaining_seconds) * 1000),
                "cooldown_skipped": any(
                    item.get("cooldown_skipped") or item.get("failure_category") == "cooldown_skipped"
                    for item in attempts
                ),
            }
        )
        if extra:
            metrics.update(extra)
        return metrics

    def _record_success(self, leaf: Any, *, fallback_occurred: bool, attempts: list[dict[str, Any]], http_attempts: int) -> None:
        metrics = self._metrics_from_attempts(attempts, leaf=leaf, fallback_occurred=fallback_occurred)
        metrics["attempt"] = http_attempts
        self.last_call_metrics = metrics
        self.last_attempt_count = http_attempts
        leaf.last_call_metrics = metrics

    def _invoke(self, method: str, payload: dict) -> Any:
        last_error: LLMProviderError | None = None
        http_attempts = 0
        cap = len(self._providers) * 2
        attempted_index: int | None = None
        logical_attempts: list[dict[str, Any]] = []
        for index, leaf in enumerate(self._providers):
            if _in_cooldown(leaf.provider_name):
                logger.info("Skipping AI provider in cooldown provider=%s", leaf.provider_name)
                logical_attempts.append(
                    self._admission_record(
                        leaf,
                        method=method,
                        failure_category="cooldown_skipped",
                        http_status_class="cooldown",
                        cooldown_skipped=True,
                        fallback=index > 0,
                    )
                )
                continue
            if self._remaining_seconds <= 0:
                if logical_attempts:
                    self.last_call_metrics = self._metrics_from_attempts(
                        logical_attempts,
                        leaf=leaf,
                        fallback_occurred=index > 0,
                    )
                raise last_error or ProviderTimeoutError("Investigation provider budget exceeded")
            if not budget_allows_attempt(self._remaining_seconds, self._timeout_seconds):
                logical_attempts.append(
                    self._admission_record(
                        leaf,
                        method=method,
                        failure_category="budget_too_small",
                        http_status_class="skip",
                        fallback=index > 0,
                    )
                )
                last_error = last_error or ProviderTimeoutError("Investigation provider budget exceeded")
                self.last_call_metrics = self._metrics_from_attempts(
                    logical_attempts,
                    leaf=leaf,
                    fallback_occurred=index > 0,
                )
                continue
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
                logical_attempts.extend(
                    self._stamp_attempts(self._leaf_attempts(leaf, exc), method=method, fallback=index > 0)
                )
                self.last_call_metrics = self._metrics_from_attempts(
                    logical_attempts,
                    leaf=leaf,
                    fallback_occurred=index > 0,
                )
                logger.error(
                    "AI provider failover candidate failed provider=%s category=%s attempt_total=%s/%s",
                    leaf.provider_name,
                    type(exc).__name__,
                    http_attempts,
                    cap,
                )
                if isinstance(exc, (ProviderRateLimitError, ProviderTimeoutError)):
                    _mark_cooldown(leaf.provider_name)
                if isinstance(exc, ProviderTimeoutError) and self._remaining_seconds <= 0:
                    raise
                continue
            except Exception as exc:
                mapped = exc if isinstance(exc, LLMProviderError) else LLMProviderError("AI provider structured response failed")
                self._sync_budget(leaf)
                used = max(1, int(getattr(leaf, "last_attempt_count", 1) or 1))
                http_attempts += used
                last_error = mapped
                logical_attempts.extend(
                    self._stamp_attempts(self._leaf_attempts(leaf, mapped), method=method, fallback=index > 0)
                )
                self.last_call_metrics = self._metrics_from_attempts(
                    logical_attempts,
                    leaf=leaf,
                    fallback_occurred=index > 0,
                )
                continue
            self._sync_budget(leaf)
            used = max(1, int(getattr(leaf, "last_attempt_count", 1) or 1))
            http_attempts += used
            logical_attempts.extend(
                self._stamp_attempts(self._leaf_attempts(leaf), method=method, fallback=index > 0)
            )
            self._record_success(
                leaf,
                fallback_occurred=index > 0 or attempted_index != 0,
                attempts=logical_attempts,
                http_attempts=http_attempts,
            )
            return result
        if logical_attempts:
            leaf = self._providers[-1]
            self.last_call_metrics = self._metrics_from_attempts(
                logical_attempts,
                leaf=leaf,
                fallback_occurred=True,
            )
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

    timeout_seconds = float(getattr(settings, "ai_provider_timeout_seconds", 15) or 15)
    budget_seconds = float(getattr(settings, "ai_investigation_llm_budget_seconds", 30) or 30)
    configured_attempts = int(getattr(settings, "ai_provider_max_attempts", 2) or 2)
    multi = explicit_order or len(order) > 1
    max_leaf_attempts = 1 if multi else configured_attempts

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
