"""Run one persisted-data LangGraph evaluation case.

Examples (from ``backend``):

    python scripts/evaluate_ai.py --case clear_equipment_failure
    python scripts/evaluate_ai.py --case connectivity_loss --json
    python scripts/evaluate_ai.py --case ambiguous_stop --real-llm

The default deterministic provider costs nothing and evaluates pipeline
correctness only. ``--real-llm`` is opt-in and may incur provider charges.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_eval.cases import EVALUATION_CASES
from ai_eval.reporting import format_report
from ai_eval.runner import run_evaluation
from app.ai.llm.provider import LLMProviderError
from app.db.database import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=sorted(EVALUATION_CASES), default="clear_equipment_failure")
    parser.add_argument("--site-code", help="Select a site when equipment codes exist at multiple sites")
    parser.add_argument("--real-llm", action="store_true", help="Use configured provider; may incur API charges")
    parser.add_argument("--json", action="store_true", help="Print the full machine-readable report")
    parser.add_argument("--list", action="store_true", help="List cases without running an investigation")
    args = parser.parse_args()
    if args.list:
        for case_id, case in EVALUATION_CASES.items():
            print(f"{case_id}: {case.description}")
        return 0
    if args.real_llm:
        print(
            "WARNING: --real-llm invokes the configured provider and may incur API usage; "
            "one investigation will be run.",
            file=sys.stderr,
        )
    try:
        with SessionLocal() as session:
            report = run_evaluation(
                session,
                args.case,
                real_llm=args.real_llm,
                site_code=args.site_code,
            )
        print(report.model_dump_json(indent=2) if args.json else format_report(report))
        return 0 if report.pipeline_correct else 1
    except Exception as exc:
        # Detailed traceback remains available through normal server/test logging.
        if isinstance(exc, LLMProviderError):
            outcome = "PROVIDER_FAILURE"
        elif isinstance(exc, LookupError):
            outcome = "MISSING_OPERATIONAL_DATA"
        else:
            outcome = "INTEGRATION_FAILURE"
        print(
            json.dumps(
                {
                    "case_id": args.case,
                    "outcome": outcome,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
