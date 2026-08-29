#!/usr/bin/env python3
"""Read-only audit of persisted haul-truck cycles for Predictive Intelligence V1.

Does not mutate data, train a model, or call an LLM.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.database import SessionLocal


def _pct(part: int, whole: int) -> float | None:
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 1)


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "p90": None, "p99": None, "max": None, "mean": None}
    ordered = sorted(values)
    n = len(ordered)

    def at(p: float) -> float:
        idx = min(n - 1, max(0, math.ceil(p * n) - 1))
        return round(ordered[idx], 2)

    return {
        "min": round(ordered[0], 2),
        "p25": at(0.25),
        "median": at(0.5),
        "p75": at(0.75),
        "p90": at(0.90),
        "p99": at(0.99),
        "max": round(ordered[-1], 2),
        "mean": round(sum(ordered) / n, 2),
    }


def main() -> int:
    report: dict = {"source": "MinePulse PostgreSQL (read-only)", "synthetic": True}
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))

        def scalar(sql: str, **params):
            return session.execute(text(sql), params).scalar()

        report["counts"] = {
            "cycles_total": int(scalar("SELECT COUNT(*) FROM cycles") or 0),
            "cycles_completed": int(scalar("SELECT COUNT(*) FROM cycles WHERE status = 'COMPLETED'") or 0),
            "cycles_active": int(scalar("SELECT COUNT(*) FROM cycles WHERE status = 'ACTIVE'") or 0),
            "cycles_other_status": int(scalar("SELECT COUNT(*) FROM cycles WHERE status NOT IN ('ACTIVE', 'COMPLETED')") or 0),
            "cycle_stages": int(scalar("SELECT COUNT(*) FROM cycle_stages") or 0),
            "trips": int(scalar("SELECT COUNT(*) FROM trips") or 0),
            "assignments": int(scalar("SELECT COUNT(*) FROM equipment_assignments") or 0),
            "haul_roads": int(scalar("SELECT COUNT(*) FROM haul_roads") or 0),
            "equipment": int(scalar("SELECT COUNT(*) FROM equipment") or 0),
            "shifts": int(scalar("SELECT COUNT(*) FROM shifts") or 0),
            "alerts": int(scalar("SELECT COUNT(*) FROM alerts") or 0),
            "telemetry_rows": int(scalar("SELECT COUNT(*) FROM equipment_telemetry") or 0),
            "equipment_states": int(scalar("SELECT COUNT(*) FROM equipment_states") or 0),
            "predictions_table": int(scalar("SELECT COUNT(*) FROM predictions") or 0),
        }

        completed = report["counts"]["cycles_completed"]
        report["missing"] = {
            "completed_null_loader": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND loader_id IS NULL") or 0),
            "completed_null_origin": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND origin_zone_id IS NULL") or 0),
            "completed_null_destination": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND destination_zone_id IS NULL") or 0),
            "completed_null_duration": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND total_duration_sec IS NULL") or 0),
            "completed_null_completed_at": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND completed_at IS NULL") or 0),
            "completed_null_payload": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND payload_t IS NULL") or 0),
            "completed_null_distance": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND distance_km IS NULL") or 0),
            "completed_null_shift": int(scalar("SELECT COUNT(*) FROM cycles WHERE status='COMPLETED' AND shift_id IS NULL") or 0),
            "haul_roads_null_grade": int(scalar("SELECT COUNT(*) FROM haul_roads WHERE road_grade_pct IS NULL") or 0),
            "haul_roads_null_quality": int(scalar("SELECT COUNT(*) FROM haul_roads WHERE road_quality IS NULL") or 0),
            "haul_roads_null_distance": int(scalar("SELECT COUNT(*) FROM haul_roads WHERE distance_km IS NULL") or 0),
        }
        report["missing_rates_pct"] = {
            key: _pct(value, completed if key.startswith("completed_") else report["counts"]["haul_roads"])
            for key, value in report["missing"].items()
        }

        duration_rows = session.execute(
            text(
                """
                SELECT total_duration_sec / 60.0 AS minutes
                FROM cycles
                WHERE status = 'COMPLETED' AND total_duration_sec IS NOT NULL
                """
            )
        ).scalars().all()
        minutes = [float(v) for v in duration_rows]
        report["duration_minutes"] = _quantiles(minutes)
        report["duration_outliers"] = {
            "lte_0": sum(1 for v in minutes if v <= 0),
            "lt_5": sum(1 for v in minutes if v < 5),
            "gt_180": sum(1 for v in minutes if v > 180),
            "gt_300": sum(1 for v in minutes if v > 300),
            "duration_mismatch_gt_5s": int(
                scalar(
                    """
                    SELECT COUNT(*) FROM cycles
                    WHERE status = 'COMPLETED'
                      AND started_at IS NOT NULL AND completed_at IS NOT NULL
                      AND total_duration_sec IS NOT NULL
                      AND ABS(total_duration_sec - EXTRACT(EPOCH FROM (completed_at - started_at))) > 5
                    """
                )
                or 0
            ),
        }

        span = session.execute(
            text(
                """
                SELECT MIN(started_at), MAX(started_at), MIN(completed_at), MAX(completed_at)
                FROM cycles WHERE status = 'COMPLETED'
                """
            )
        ).one()
        report["time_span"] = {
            "min_started_at": span[0].isoformat() if span[0] else None,
            "max_started_at": span[1].isoformat() if span[1] else None,
            "min_completed_at": span[2].isoformat() if span[2] else None,
            "max_completed_at": span[3].isoformat() if span[3] else None,
        }

        def grouped(sql: str) -> list[dict]:
            rows = session.execute(text(sql)).mappings().all()
            return [dict(row) for row in rows]

        report["by_truck"] = grouped(
            """
            SELECT e.code AS truck, COUNT(*) AS n,
                   ROUND(AVG(c.total_duration_sec / 60.0)::numeric, 1) AS mean_min,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY c.total_duration_sec / 60.0)::numeric, 1) AS median_min
            FROM cycles c JOIN equipment e ON e.equipment_id = c.truck_id
            WHERE c.status = 'COMPLETED' AND c.total_duration_sec IS NOT NULL
            GROUP BY e.code ORDER BY n DESC, e.code
            """
        )
        report["by_loader"] = grouped(
            """
            SELECT COALESCE(e.code, 'NULL') AS loader, COUNT(*) AS n,
                   ROUND(AVG(c.total_duration_sec / 60.0)::numeric, 1) AS mean_min,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY c.total_duration_sec / 60.0)::numeric, 1) AS median_min
            FROM cycles c LEFT JOIN equipment e ON e.equipment_id = c.loader_id
            WHERE c.status = 'COMPLETED' AND c.total_duration_sec IS NOT NULL
            GROUP BY e.code ORDER BY n DESC
            """
        )
        report["by_origin"] = grouped(
            """
            SELECT COALESCE(z.code, 'NULL') AS origin, COUNT(*) AS n,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY c.total_duration_sec / 60.0)::numeric, 1) AS median_min
            FROM cycles c LEFT JOIN zones z ON z.zone_id = c.origin_zone_id
            WHERE c.status = 'COMPLETED' AND c.total_duration_sec IS NOT NULL
            GROUP BY z.code ORDER BY n DESC
            """
        )
        report["by_destination"] = grouped(
            """
            SELECT COALESCE(z.code, 'NULL') AS destination, COUNT(*) AS n,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY c.total_duration_sec / 60.0)::numeric, 1) AS median_min
            FROM cycles c LEFT JOIN zones z ON z.zone_id = c.destination_zone_id
            WHERE c.status = 'COMPLETED' AND c.total_duration_sec IS NOT NULL
            GROUP BY z.code ORDER BY n DESC
            """
        )
        report["by_route"] = grouped(
            """
            SELECT COALESCE(o.code, 'NULL') AS origin, COALESCE(d.code, 'NULL') AS destination, COUNT(*) AS n,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY c.total_duration_sec / 60.0)::numeric, 1) AS median_min
            FROM cycles c
            LEFT JOIN zones o ON o.zone_id = c.origin_zone_id
            LEFT JOIN zones d ON d.zone_id = c.destination_zone_id
            WHERE c.status = 'COMPLETED' AND c.total_duration_sec IS NOT NULL
            GROUP BY o.code, d.code ORDER BY n DESC
            """
        )
        report["by_shift"] = grouped(
            """
            SELECT s.shift_id, s.shift_date::text, s.name, COUNT(*) AS n,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY c.total_duration_sec / 60.0)::numeric, 1) AS median_min
            FROM cycles c JOIN shifts s ON s.shift_id = c.shift_id
            WHERE c.status = 'COMPLETED' AND c.total_duration_sec IS NOT NULL
            GROUP BY s.shift_id, s.shift_date, s.name ORDER BY s.shift_date, s.name
            """
        )
        report["start_stage"] = grouped(
            """
            SELECT cs.stage::text AS first_stage, COUNT(*) AS n
            FROM cycles c
            JOIN cycle_stages cs ON cs.cycle_id = c.cycle_id AND cs.sequence_no = (
                SELECT MIN(sequence_no) FROM cycle_stages WHERE cycle_id = c.cycle_id
            )
            WHERE c.status = 'COMPLETED'
            GROUP BY cs.stage ORDER BY n DESC
            """
        )
        report["status_counts"] = dict(
            session.execute(text("SELECT status, COUNT(*) FROM cycles GROUP BY status")).all()
        )

        histogram = Counter()
        for value in minutes:
            if value < 30:
                histogram["<30"] += 1
            elif value < 40:
                histogram["30-40"] += 1
            elif value < 50:
                histogram["40-50"] += 1
            elif value < 70:
                histogram["50-70"] += 1
            elif value < 100:
                histogram["70-100"] += 1
            else:
                histogram["100+"] += 1
        report["duration_histogram"] = dict(histogram)
        report["usable_v1_samples"] = int(
            scalar(
                """
                SELECT COUNT(*) FROM cycles
                WHERE status = 'COMPLETED'
                  AND started_at IS NOT NULL
                  AND completed_at IS NOT NULL
                  AND total_duration_sec IS NOT NULL
                  AND total_duration_sec > 0
                  AND truck_id IS NOT NULL
                """
            )
            or 0
        )
        report["usable_v1_with_route_and_loader"] = int(
            scalar(
                """
                SELECT COUNT(*) FROM cycles
                WHERE status = 'COMPLETED'
                  AND started_at IS NOT NULL
                  AND completed_at IS NOT NULL
                  AND total_duration_sec > 0
                  AND truck_id IS NOT NULL
                  AND loader_id IS NOT NULL
                  AND origin_zone_id IS NOT NULL
                  AND destination_zone_id IS NOT NULL
                """
            )
            or 0
        )

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
