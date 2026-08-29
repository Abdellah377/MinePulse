#!/usr/bin/env python3
"""Compare live database schema against expected MinePulse tables/enums."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.database import engine
from scripts import EXPECTED_COLUMNS, EXPECTED_ENUMS, EXPECTED_TABLES


def main() -> int:
    exit_code = 0

    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            )
        }
        enums = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT t.typname FROM pg_type t "
                    "JOIN pg_enum e ON t.oid = e.enumtypid "
                    "GROUP BY t.typname"
                )
            )
        }

        missing_tables = sorted(EXPECTED_TABLES - tables)
        extra_tables = sorted(tables - EXPECTED_TABLES - {"spatial_ref_sys"})
        missing_enums = sorted(EXPECTED_ENUMS - enums)
        columns_by_table = {
            table: {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :table"
                    ),
                    {"table": table},
                )
            }
            for table in EXPECTED_COLUMNS
        }
        missing_columns = {
            table: sorted(expected - columns_by_table[table])
            for table, expected in EXPECTED_COLUMNS.items()
            if expected - columns_by_table[table]
        }

        print("=== Schema verification ===")
        print(f"Expected tables: {len(EXPECTED_TABLES)} | Found: {len(tables & EXPECTED_TABLES)}")

        if missing_tables:
            exit_code = 1
            print(f"MISSING tables ({len(missing_tables)}): {', '.join(missing_tables)}")
        else:
            print("All expected tables present.")

        if missing_enums:
            exit_code = 1
            print(f"MISSING enums ({len(missing_enums)}): {', '.join(missing_enums)}")
        else:
            print("All expected enums present.")

        if missing_columns:
            exit_code = 1
            for table, columns in sorted(missing_columns.items()):
                print(f"MISSING columns in {table}: {', '.join(columns)}")
        else:
            print("All expected incremental columns present.")

        if extra_tables:
            print(f"Extra tables (not in plan): {', '.join(extra_tables)}")

        views = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.views "
                    "WHERE table_schema = 'public'"
                )
            )
        ]
        print(f"Views: {', '.join(sorted(views)) if views else '(none)'}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
