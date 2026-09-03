"""Opt-in optimization workflow latency timelines. Never invoked by pytest.

From backend/:

    python -m scripts.benchmark_optimization_latency --mock
    python -m scripts.benchmark_optimization_latency --live --i-understand-this-costs-money
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.llm.provider import ProviderTimeoutError
from app.ai.llm.router import ProviderRouter, clear_provider_cooldowns
from app.ai.optimization.workflow import format_optimization_timeline
from app.optimization.contracts import (
    OptimizationPlannerDecision,
    OptimizationReview,
    OptimizerId,
    ProblemType,
    ReviewStatus,
)


class _BenchLeaf:
    def __init__(self, name: str, *, cost_s: float, ok: bool):
        self.provider_name = name
        self.model_name = "bench-model"
        self._remaining_seconds = 30
        self._timeout_seconds = 15
        self._max_attempts = 1
        self.last_attempt_count = 0
        self.last_call_metrics = None
        self.invocations = 0
        self._cost_s = cost_s
        self._ok = ok
        self._planner = OptimizationPlannerDecision(
            selected_optimizers=[OptimizerId.DISPATCH_LOADER],
            problem_type=ProblemType.CONGESTION_RISK,
        )
        self._review = OptimizationReview(status=ReviewStatus.APPROVED)

    def _run(self, method, payload):
        self.invocations += 1
        self._remaining_seconds -= self._cost_s
        duration_ms = int(self._cost_s * 1000)
        record = {
            "provider": self.provider_name,
            "model": self.model_name,
            "attempt": 1,
            "duration_ms": duration_ms,
            "http_status_class": "ok" if self._ok else "timeout",
            "failure_category": None if self._ok else "ProviderTimeoutError",
            "parse_retry": False,
            "remaining_budget_ms": int(max(0.0, self._remaining_seconds) * 1000),
        }
        self.last_attempt_count = 1
        self.last_call_metrics = {
            "provider": self.provider_name,
            "model": self.model_name,
            "duration_ms": duration_ms,
            "attempts": [record],
            "remaining_budget_ms": record["remaining_budget_ms"],
            "fallback_occurred": False,
        }
        if not self._ok:
            raise ProviderTimeoutError("timeout")
        if method == "plan_optimization":
            return self._planner
        return self._review

    def plan_optimization(self, payload):
        return self._run("plan_optimization", payload)

    def review_optimization(self, payload):
        return self._run("review_optimization", payload)


def _mock_case(*, timeout_s: float, budget_s: float, label: str, plan_ok: bool, review_ok: bool, healthy_s: float = 0.8) -> dict:
    groq_cost = healthy_s if plan_ok else timeout_s
    groq = _BenchLeaf("groq", cost_s=groq_cost, ok=plan_ok)
    gemini = _BenchLeaf("gemini", cost_s=healthy_s, ok=True)
    router = ProviderRouter(
        [groq, gemini],
        budget_seconds=budget_s,
        timeout_seconds=timeout_s,
        max_leaf_attempts=1,
    )
    planner_ms = 0
    reviewer_ms = 0
    planner_error = None
    reviewer_error = None
    try:
        router.plan_optimization({"alertType": "CONGESTION_RISK"})
        planner_ms = int((router.last_call_metrics or {}).get("duration_ms") or 0)
    except Exception as exc:
        planner_error = type(exc).__name__
        planner_ms = int((router.last_call_metrics or {}).get("duration_ms") or 0)
    if planner_error is None:
        try:
            router.review_optimization({"candidates": []})
            reviewer_ms = int((router.last_call_metrics or {}).get("duration_ms") or 0)
        except Exception as exc:
            reviewer_error = type(exc).__name__
            reviewer_ms = int((router.last_call_metrics or {}).get("duration_ms") or 0)
    total = planner_ms + reviewer_ms
    snapshot = {
        "workflow": {
            "workflowStatus": "ORCHESTRATED" if not planner_error and not reviewer_error else (
                "DETERMINISTIC_ONLY" if planner_error else "REVIEW_UNAVAILABLE"
            ),
            "optimizationPassCount": 1,
            "planner": router.last_call_metrics or {},
            "reviewer": {"failed": bool(reviewer_error)},
            "timings": {
                "optimization_total_ms": total,
                "planner_ms": planner_ms,
                "reviewer_pass_1_ms": reviewer_ms,
                "engine_pass_1_ms": 8,
                "weather_ms": 4,
                "trusted_input_ms": 12,
                "persist_ms": 6,
            },
        }
    }
    print(f"{label}: planner_error={planner_error} reviewer_error={reviewer_error}")
    print(format_optimization_timeline(snapshot))
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--i-understand-this-costs-money", action="store_true")
    args = parser.parse_args()
    if not (args.mock or args.live):
        parser.error("Choose --mock and/or --live")
    if args.mock:
        clear_provider_cooldowns()
        print("BEFORE (unbounded 45s timeouts sharing a 150s budget would allow multi-minute waits)")
        _mock_case(timeout_s=45, budget_s=150, label="before-timeout-pair", plan_ok=False, review_ok=False)
        clear_provider_cooldowns()
        print("AFTER (15s timeout, 30s shared planner+reviewer budget)")
        _mock_case(timeout_s=15, budget_s=30, label="after-timeout-pair", plan_ok=False, review_ok=False)
        clear_provider_cooldowns()
        print("HEALTHY (planner+reviewer success, ~4s each)")
        _mock_case(timeout_s=15, budget_s=30, label="healthy", plan_ok=True, review_ok=True, healthy_s=4.0)
    if args.live:
        if not args.i_understand_this_costs_money:
            parser.error("--live requires --i-understand-this-costs-money")
        print("Live optimization benchmark is opt-in and not run from pytest.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
