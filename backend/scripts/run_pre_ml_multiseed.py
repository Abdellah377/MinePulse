#!/usr/bin/env python3
"""Create, use, audit, and remove one isolated local PostgreSQL audit DB.

The configured MinePulse database is used only as a connection template. All
generation and migrations target a uniquely prefixed disposable database.
The database is dropped in ``finally``; the JSON report remains outside it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

from scripts.pre_ml_audit import (
    AUDIT_DATABASE_PREFIX,
    AuditDatabaseError,
    audit_database,
    resolve_audit_database_url,
    summarize_seed_reports,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_SCHEMA = BACKEND_ROOT.parent / "shema_postgre" / "minepulse_schema.sql"
SCHEMA_BASELINE_REVISION = "20260825_trigger_semantics"
_SAFE_DATABASE_NAME = re.compile(r"^minepulse_audit_[a-z0-9_]+$")


def new_audit_database_name(*, token: str | None = None) -> str:
    token = token or f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
    name = f"{AUDIT_DATABASE_PREFIX}{token.lower()}"
    if not _SAFE_DATABASE_NAME.fullmatch(name):
        raise AuditDatabaseError("Generated audit database name contains unsafe characters.")
    return name


def _validated_name(name: str) -> str:
    if not _SAFE_DATABASE_NAME.fullmatch(name):
        raise AuditDatabaseError(
            f"Managed database name must match {_SAFE_DATABASE_NAME.pattern!r}."
        )
    return name


def _admin_url(configured: URL) -> URL:
    if configured.database in {"postgres", "template0", "template1"}:
        raise AuditDatabaseError(
            "Configured MinePulse DB must not be a PostgreSQL administrative database."
        )
    return configured.set(database="postgres")


def create_database(admin_url: URL, database_name: str) -> None:
    name = _validated_name(database_name)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        engine.dispose()


def drop_database(admin_url: URL, database_name: str) -> None:
    name = _validated_name(database_name)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        engine.dispose()


def _database_environment(audit_url: URL) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "DB_HOST": audit_url.host or "localhost",
            "DB_PORT": str(audit_url.port or 5432),
            "DB_NAME": str(audit_url.database),
            "DB_USER": audit_url.username or "postgres",
            "DB_PASSWORD": audit_url.password or "",
            "MONITORING_ENABLED": "false",
        }
    )
    return environment


def _run(args: list[str], *, audit_url: URL) -> None:
    subprocess.run(
        args,
        cwd=BACKEND_ROOT,
        env=_database_environment(audit_url),
        check=True,
    )


def bootstrap_core_schema(audit_url: URL) -> None:
    """Load MinePulse's checked-in bootstrap schema into a brand-new DB."""
    schema_sql = REPOSITORY_SCHEMA.read_text(encoding="utf-8")
    engine = create_engine(audit_url, future=True)
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis", prepare=False)
        cursor.execute(schema_sql, prepare=False)
        raw.commit()
    finally:
        raw.close()
        engine.dispose()


def run_migrations(audit_url: URL) -> None:
    # This repository predates a complete Alembic core-schema revision. The
    # checked-in SQL is its authoritative bootstrap, while later additive
    # migrations remain the authoritative evolution path.
    bootstrap_core_schema(audit_url)
    _run(
        [sys.executable, "-m", "alembic", "stamp", SCHEMA_BASELINE_REVISION],
        audit_url=audit_url,
    )
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], audit_url=audit_url)


def generate_seed(audit_url: URL, *, seed: int, target_cycles: int) -> None:
    _run(
        [
            sys.executable,
            "-m",
            "simulator",
            "generate-cycles",
            "--target-cycles",
            str(target_cycles),
            "--seed",
            str(seed),
            "--sim-speed",
            "60",
            "--sample-every-ticks",
            "2",
            "--with-failures",
        ],
        audit_url=audit_url,
    )


def run_managed_audit(
    *,
    configured_url: str,
    database_name: str,
    seeds: list[int],
    target_cycles: int,
    output: Path,
) -> dict[str, object]:
    configured = make_url(configured_url)
    audit_url = configured.set(database=_validated_name(database_name))
    explicit_audit_url = audit_url.render_as_string(hide_password=False)
    resolve_audit_database_url(explicit_audit_url, configured_url=configured_url)
    admin_url = _admin_url(configured)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, object]] = []
    created = False
    try:
        create_database(admin_url, database_name)
        created = True
        run_migrations(audit_url)
        if not seeds:
            raise AuditDatabaseError("At least one seed is required.")
        first, *rest = seeds
        generate_seed(audit_url, seed=first, target_cycles=target_cycles)
        first_report = audit_database(explicit_audit_url, seed=first, configured_url=configured_url)
        generate_seed(audit_url, seed=first, target_cycles=target_cycles)
        replay_report = audit_database(explicit_audit_url, seed=first, configured_url=configured_url)
        reproducibility = {
            "seed": first,
            "same_sequence": first_report.get("sequence_fingerprint")
            == replay_report.get("sequence_fingerprint"),
            "first_fingerprint": first_report.get("sequence_fingerprint"),
            "replay_fingerprint": replay_report.get("sequence_fingerprint"),
        }
        reports.append(replay_report)
        for seed in rest:
            generate_seed(audit_url, seed=seed, target_cycles=target_cycles)
            reports.append(
                audit_database(explicit_audit_url, seed=seed, configured_url=configured_url)
            )
        payload: dict[str, object] = {
            "audit_database": {
                "name": database_name,
                "disposable": True,
                "dropped_after_run": True,
            },
            "generation": {
                "seeds": seeds,
                "target_cycles_per_seed": target_cycles,
                "failure_population_enabled": True,
            },
            "reproducibility": reproducibility,
            "summary": summarize_seed_reports(reports),
            "reports": reports,
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return payload
    finally:
        if created:
            drop_database(admin_url, database_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a multi-seed pre-ML audit in one disposable local PostgreSQL database."
    )
    parser.add_argument("--seed", type=int, action="append", required=True)
    parser.add_argument("--target-cycles", type=int, default=500)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database-name", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    args = build_parser().parse_args(argv)
    if args.target_cycles < 1:
        raise SystemExit("--target-cycles must be positive")
    database_name = args.database_name or new_audit_database_name()
    payload = run_managed_audit(
        configured_url=get_settings().database_url,
        database_name=database_name,
        seeds=list(dict.fromkeys(args.seed)),
        target_cycles=args.target_cycles,
        output=args.output,
    )
    print(
        json.dumps(
            {
                "report": str(args.output.resolve()),
                "seeds": payload["generation"]["seeds"],
                "audit_database_dropped": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
