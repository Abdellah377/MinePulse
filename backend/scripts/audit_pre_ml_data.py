#!/usr/bin/env python3
"""Run the guarded, read-only pre-ML audit against a disposable database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.pre_ml_audit import (
    AuditDatabaseError,
    audit_database,
    audit_seed_databases,
    summarize_seed_reports,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only pre-ML quality audit for a disposable MinePulse PostgreSQL database."
    )
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument(
        "--database-url",
        help="Explicit PostgreSQL URL whose database name begins minepulse_audit_.",
    )
    targets.add_argument(
        "--seed-database",
        action="append",
        default=None,
        metavar="SEED=URL",
        help="Repeat with a distinct explicit disposable URL for each generated seed.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        action="append",
        default=None,
        help="Generation seed represented by this already-populated audit database; repeat for reports.",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=None,
        help="Optional root containing existing failure_risk/ and cycle_time/ saved artifacts.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional explicit path for the JSON report (the only file this command may write).",
    )
    return parser


def _seed_urls(values: list[str]) -> dict[int, str]:
    parsed: dict[int, str] = {}
    for value in values:
        seed_text, separator, url = value.partition("=")
        if not separator or not url:
            raise AuditDatabaseError("--seed-database must use SEED=POSTGRES_URL.")
        try:
            seed = int(seed_text)
        except ValueError as exc:
            raise AuditDatabaseError("--seed-database seed must be an integer.") from exc
        if seed in parsed:
            raise AuditDatabaseError(f"Seed {seed} was supplied more than once.")
        parsed[seed] = url
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seeds: list[int | None] = args.seed or [None]
    try:
        reports = (
            audit_seed_databases(_seed_urls(args.seed_database), artifacts_root=args.artifacts_root)
            if args.seed_database
            else [
                audit_database(args.database_url, seed=seed, artifacts_root=args.artifacts_root)
                for seed in seeds
            ]
        )
    except AuditDatabaseError as exc:
        print(f"pre-ML audit refused: {exc}", file=sys.stderr)
        return 2
    payload: dict[str, object] = {
        "summary": summarize_seed_reports(reports),
        "reports": reports,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
