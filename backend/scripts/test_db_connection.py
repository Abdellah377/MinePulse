#!/usr/bin/env python3
"""Verify PostgreSQL connectivity for MinePulse backend."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.config import get_settings
from app.db.database import engine


def main() -> int:
    settings = get_settings()
    print(f"Connecting to {settings.db_host}:{settings.db_port}/{settings.db_name} ...")

    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar_one()
            print(f"PostgreSQL: {version[:80]}...")

            db_name = conn.execute(text("SELECT current_database()")).scalar_one()
            print(f"Database: {db_name}")

            postgis = conn.execute(text("SELECT PostGIS_Version()")).scalar_one_or_none()
            if postgis:
                print(f"PostGIS: {postgis}")
            else:
                print("ERROR: PostGIS extension not available.")
                return 1

            table_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            ).scalar_one()
            print(f"Public tables: {table_count}")

        print("Connection OK.")
        return 0
    except Exception as exc:
        print(f"Connection FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
