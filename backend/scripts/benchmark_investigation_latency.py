"""Opt-in investigation latency timelines. Never invoked by pytest.

From backend/:

    python -m scripts.benchmark_investigation_latency --mock
    python -m scripts.benchmark_investigation_latency --from-db --limit 5
    python -m scripts.benchmark_investigation_latency --live --i-understand-this-costs-money

``--live`` calls the configured provider and may incur API charges.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.debug import format_investigation_timeline
from app.ai.llm.provider import ProviderTimeoutError
from app.ai.llm.router import ProviderRouter, clear_provider_cooldowns


class _BenchLeaf:
    def __init__(self, name: str, *, cost_s: float = 0.0, ok: bool = False):
        from app.ai.contracts import ConfidenceLevel, DiagnosisResult

        self.provider_name = name
        self.model_name = "bench-model"
        self._remaining_seconds = 150
        self._max_attempts = 1
        self.last_attempt_count = 0
        self.last_call_metrics = None
        self.invocations = 0
        self._cost_s = cost_s
        self._ok = ok
        self._diagnosis = DiagnosisResult(
            can_conclude=False,
            confidence=ConfidenceLevel.LOW,
            confidence_rationale="benchmark",
            reasoning_summary="benchmark",
        )

    def _run(self, method, payload):
        self.invocations += 1
        attempts = max(1, int(getattr(self, "_max_attempts", 1)))
        records = []
        for attempt in range(1, attempts + 1):
            if self._cost_s:
                self._remaining_seconds -= self._cost_s
            duration_ms = int(self._cost_s * 1000)
            records.append(
                {
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "attempt": attempt,
                    "duration_ms": duration_ms,
                    "http_status_class": "ok" if self._ok else "timeout",
                    "failure_category": None if self._ok else "ProviderTimeoutError",
                    "parse_retry": False,
                    "prompt_chars": 12,
                    "evidence_count": 0,
                    "remaining_budget_ms": int(max(0.0, self._remaining_seconds) * 1000),
                }
            )
            if self._ok:
                break
        self.last_attempt_count = len(records)
        self.last_call_metrics = {
            "provider": self.provider_name,
            "model": self.model_name,
            "duration_ms": sum(item["duration_ms"] for item in records),
            "attempts": records,
        }
        if self._ok:
            return self._diagnosis
        raise ProviderTimeoutError("timeout")

    def diagnose(self, payload):
        return self._run("diagnose", payload)

    def build_conclusion(self, payload):
        return self._run("build_conclusion", payload)

    def build_recommendation(self, payload):
        return self._run("build_recommendation", payload)


def mock_timeline(*, timeout_s: float, budget_s: float, leaf_attempts: int, label: str) -> dict:
    groq = _BenchLeaf("groq", cost_s=timeout_s)
    gemini = _BenchLeaf("gemini", cost_s=timeout_s)
    openai = _BenchLeaf("openai", cost_s=0.8, ok=True)
    router = ProviderRouter(
        [groq, gemini, openai],
        budget_seconds=budget_s,
        timeout_seconds=timeout_s,
        max_leaf_attempts=leaf_attempts,
    )
    try:
        router.diagnose({"evidence": []})
        outcome = "ok"
    except Exception as exc:
        outcome = type(exc).__name__
    metrics = router.last_call_metrics or {}
    attempts = list(metrics.get("attempts") or [])
    llm_ms = sum(int(item.get("duration_ms") or 0) for item in attempts)
    dump = {
        "investigation_id": f"mock-{label}",
        "graph_version": "1.3.0",
        "provider": metrics.get("final_provider"),
        "model": metrics.get("model"),
        "wall_durations_ms": {
            "total": llm_ms,
            "llm": llm_ms,
            "evidence": 0,
            "persist": 0,
            "nodes": {"analyze": llm_ms},
        },
        "events": [
            {
                "event_type": "LLM_ATTEMPT",
                "stage": "analyze",
                "duration_ms": item.get("duration_ms"),
                "summary": f"{item.get('provider')} {item.get('http_status_class')} {item.get('duration_ms')}ms",
                "metadata": item,
            }
            for item in attempts
        ],
        "outcome": outcome,
        "fallback_occurred": metrics.get("fallback_occurred"),
        "attempt_count": len(attempts),
        "slowest_stage": "analyze",
    }
    return dump


def _print_trace(dump: dict) -> None:
    print(format_investigation_timeline(dump))
    durations = dump.get("wall_durations_ms") or {}
    total = durations.get("total") or 0
    llm = durations.get("llm") or 0
    share = (100.0 * llm / total) if total else 0.0
    print(f"outcome={dump.get('outcome')} fallback={dump.get('fallback_occurred')} llm_share={share:.1f}%")
    print()


def _from_db(limit: int) -> int:
    from sqlalchemy import desc, select

    from app.db.database import SessionLocal
    from app.db.models import AiInvestigation

    with SessionLocal() as session:
        rows = session.scalars(
            select(AiInvestigation)
            .where(AiInvestigation.debug_trace.is_not(None))
            .order_by(desc(AiInvestigation.created_at))
            .limit(limit)
        ).all()
    if not rows:
        print("No ai_investigations.debug_trace rows found.")
        return 0
    for row in rows:
        dump = dict(row.debug_trace or {})
        dump.setdefault("investigation_id", str(row.investigation_id))
        durations = dump.get("wall_durations_ms") or {}
        print(
            f"# db status={row.status} iterations={row.iteration_count} "
            f"provider={row.provider} total_ms={durations.get('total')}"
        )
        _print_trace(dump)
    return 0


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _live(count: int) -> int:
    from app.ai.service import run_investigation
    from app.config import get_settings
    from app.db.database import SessionLocal
    from app.services.operational.alerts import list_site_alerts
    from app.services.operational.context import get_operational_context
    from app.ai.contracts import InvestigationTrigger, TriggerSource, TriggerType

    settings = get_settings()
    totals: list[float] = []
    with SessionLocal() as session:
        ctx = get_operational_context(session)
        alerts = list(list_site_alerts(session, ctx) or [])[: max(1, count)]
        if not alerts:
            print("No operational alerts available for a live run.")
            return 1
        for index, alert in enumerate(alerts):
            trigger = InvestigationTrigger(
                trigger_type=TriggerType.PRODUCTION_DEVIATION,
                trigger_source=TriggerSource.USER_INVESTIGATE,
                source="latency-benchmark",
                site_id=ctx.site_id,
                shift_id=ctx.shift_id,
                occurred_at=ctx.sim_now,
                source_record_id=f"bench:{getattr(alert, 'alert_id', index)}",
                equipment_id=getattr(alert, "equipment_id", None),
                zone_id=getattr(alert, "zone_id", None),
                payload={},
            )
            result = run_investigation(session, trigger)
            print(
                json.dumps(
                    {
                        "investigation_id": str(result.investigation_id),
                        "status": result.status.value if hasattr(result.status, "value") else result.status,
                        "provider": result.provider,
                        "model": result.model,
                    }
                )
            )
            from app.db.models import AiInvestigation

            persisted = session.get(AiInvestigation, result.investigation_id)
            dump = dict(getattr(persisted, "debug_trace", None) or {})
            if dump:
                total = (dump.get("wall_durations_ms") or {}).get("total")
                if isinstance(total, (int, float)):
                    totals.append(float(total))
                _print_trace(dump)
    if totals:
        seconds = [item / 1000.0 for item in totals]
        print(
            json.dumps(
                {
                    "n": len(seconds),
                    "min_s": min(seconds),
                    "p50_s": _percentile(seconds, 0.5),
                    "p95_s": _percentile(seconds, 0.95),
                    "max_s": max(seconds),
                    "mean_s": statistics.mean(seconds),
                    "budget_s": settings.ai_investigation_llm_budget_seconds,
                    "timeout_s": settings.ai_provider_timeout_seconds,
                },
                indent=2,
            )
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", help="Print reconstructed before/after failover timelines")
    parser.add_argument("--from-db", action="store_true", help="Print timelines from persisted debug_trace rows")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--live", action="store_true", help="Paid live investigations; requires confirmation flag")
    parser.add_argument("--i-understand-this-costs-money", action="store_true")
    parser.add_argument("--live-count", type=int, default=3)
    args = parser.parse_args()
    if not (args.mock or args.from_db or args.live):
        parser.error("Choose --mock, --from-db, and/or --live")
    if args.mock:
        print("BEFORE (45s timeout, 150s budget, 2 leaf attempts — architectural worst case)")
        clear_provider_cooldowns()
        before = mock_timeline(timeout_s=45, budget_s=150, leaf_attempts=2, label="before")
        _print_trace(before)
        print("AFTER (15s timeout, 30s budget, 1 leaf attempt, skip remaining < timeout)")
        clear_provider_cooldowns()
        after = mock_timeline(timeout_s=15, budget_s=30, leaf_attempts=1, label="after")
        _print_trace(after)
    if args.from_db:
        try:
            _from_db(args.limit)
        except Exception as exc:
            print(f"from-db unavailable: {type(exc).__name__}")
            return 1
    if args.live:
        if not args.i_understand_this_costs_money:
            parser.error("--live requires --i-understand-this-costs-money")
        return _live(args.live_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
