#!/usr/bin/env python3
"""Read-only audit of persisted equipment data for Failure-Risk / PdM V1.

Does not mutate data, train a model, call an LLM, or import simulator internals.
Labels are reconstructed only from operational Postgres rows.

PROTOTYPE / SYNTHETIC-DATA snapshot — not field-validated.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import bindparam, text

from app.db.database import SessionLocal
from app.oem.catalog import EVENT_TYPE_TO_CODE
from app.oem.thresholds import classify_value

INCIDENT_MERGE_GAP = timedelta(minutes=5)
NEGATIVE_STRIDE = timedelta(minutes=15)
HORIZONS_MIN = (5, 15, 30, 60)
MAX_PRECURSOR_MIN = 60
TELEMETRY_WARN_KEYS = (
    "engine_temp_c",
    "coolant_temp_c",
    "oil_pressure_kpa",
    "battery_voltage",
    "fuel_rate_lph",
    "communication_quality",
)


def _pct(part: int, whole: int) -> float | None:
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 1)


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p99": None,
            "max": None,
            "mean": None,
            "n": 0,
        }
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
        "n": n,
    }


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _iso(ts: datetime | None) -> str | None:
    ts = _aware(ts)
    return ts.isoformat() if ts else None


def _merge_mechanical_intervals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse adjacent STOPPED_MECHANICAL intervals into incidents."""
    incidents: list[dict[str, Any]] = []
    for row in rows:
        start = _aware(row["start_time"])
        end = _aware(row["end_time"])
        if start is None:
            continue
        if incidents:
            prev = incidents[-1]
            gap_ok = False
            if prev["equipment_id"] == row["equipment_id"] and prev["end_time"] is not None:
                gap_ok = start - prev["end_time"] <= INCIDENT_MERGE_GAP
            if gap_ok:
                prev["end_time"] = end if end is None or prev["end_time"] is None else max(prev["end_time"], end)
                prev["state_ids"].append(row["state_id"])
                prev["raw_interval_count"] += 1
                if row["reason_code"]:
                    prev["reason_codes"].append(row["reason_code"])
                continue
        incidents.append(
            {
                "incident_id": f"{row['equipment_id']}:{start.isoformat()}",
                "equipment_id": row["equipment_id"],
                "code": row["code"],
                "equipment_type": row["equipment_type"],
                "start_time": start,
                "end_time": end,
                "reason_codes": [row["reason_code"]] if row["reason_code"] else [],
                "state_ids": [row["state_id"]],
                "raw_interval_count": 1,
            }
        )
    return incidents


def _covers(incidents: list[dict[str, Any]], equipment_id: int, ts: datetime) -> bool:
    for item in incidents:
        if item["equipment_id"] != equipment_id:
            continue
        start = item["start_time"]
        end = item["end_time"]
        if ts >= start and (end is None or ts < end):
            return True
    return False


def _failure_in_horizon(
    incidents: list[dict[str, Any]],
    equipment_id: int,
    ts: datetime,
    horizon: timedelta,
) -> bool:
    until = ts + horizon
    for item in incidents:
        if item["equipment_id"] != equipment_id:
            continue
        start = item["start_time"]
        if ts < start <= until:
            return True
    return False


def _row_warn_keys(row: dict[str, Any]) -> list[str]:
    flagged: list[str] = []
    for key in TELEMETRY_WARN_KEYS:
        value = row.get(key)
        if value is None:
            continue
        if classify_value(key, float(value)) in {"warning", "critical"}:
            flagged.append(key)
    return flagged


def main() -> int:
    report: dict[str, Any] = {
        "source": "MinePulse PostgreSQL (read-only)",
        "synthetic": True,
        "synthetic_data_warning": (
            "This audit reads the current MinePulse snapshot, which is generated by "
            "the simulator. It is not field-validated. Hidden causal scenario ids are "
            "intentionally not queried."
        ),
        "label_definition": {
            "positive_incident": "merged contiguous equipment_states STOPPED_MECHANICAL",
            "merge_gap_minutes": INCIDENT_MERGE_GAP.total_seconds() / 60.0,
            "prediction_timestamp": "window start T; features must use data with ts <= T",
            "excluded_from_mechanical_target": [
                "STOPPED_UNDEFINED",
                "NO_DATA",
                "MAINTENANCE",
                "STOPPED_EXTERNAL",
            ],
            "forbidden_features": [
                "scenario_id",
                "hidden_root_cause",
                "run_id",
                "performance_factor",
                "scenario_*_target",
                "progress",
                "stage",
            ],
        },
        "horizons_min": list(HORIZONS_MIN),
        "negative_stride_minutes": NEGATIVE_STRIDE.total_seconds() / 60.0,
    }

    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))

        def scalar(sql: str, **params):
            return session.execute(text(sql), params).scalar()

        def grouped(sql: str, **params) -> list[dict[str, Any]]:
            return [dict(row) for row in session.execute(text(sql), params).mappings().all()]

        report["counts"] = {
            "equipment": int(scalar("SELECT COUNT(*) FROM equipment") or 0),
            "equipment_with_commission_date": int(
                scalar("SELECT COUNT(*) FROM equipment WHERE commission_date IS NOT NULL") or 0
            ),
            "telemetry_rows": int(scalar("SELECT COUNT(*) FROM equipment_telemetry") or 0),
            "tyre_telemetry_rows": int(scalar("SELECT COUNT(*) FROM tyre_telemetry") or 0),
            "equipment_states": int(scalar("SELECT COUNT(*) FROM equipment_states") or 0),
            "stopped_mechanical_intervals": int(
                scalar("SELECT COUNT(*) FROM equipment_states WHERE state = 'STOPPED_MECHANICAL'") or 0
            ),
            "stopped_undefined_intervals": int(
                scalar("SELECT COUNT(*) FROM equipment_states WHERE state = 'STOPPED_UNDEFINED'") or 0
            ),
            "no_data_intervals": int(
                scalar("SELECT COUNT(*) FROM equipment_states WHERE state = 'NO_DATA'") or 0
            ),
            "maintenance_state_intervals": int(
                scalar("SELECT COUNT(*) FROM equipment_states WHERE state = 'MAINTENANCE'") or 0
            ),
            "maintenance_events": int(scalar("SELECT COUNT(*) FROM maintenance_events") or 0),
            "downtime_events": int(scalar("SELECT COUNT(*) FROM downtime_events") or 0),
            "alerts": int(scalar("SELECT COUNT(*) FROM alerts") or 0),
            "system_events": int(scalar("SELECT COUNT(*) FROM system_events") or 0),
            "cycles_completed": int(scalar("SELECT COUNT(*) FROM cycles WHERE status = 'COMPLETED'") or 0),
        }

        report["states_by_type"] = grouped(
            "SELECT state::text AS state, COUNT(*) AS n FROM equipment_states GROUP BY 1 ORDER BY n DESC"
        )
        report["state_reason_codes"] = grouped(
            """
            SELECT COALESCE(reason_code, 'NULL') AS reason_code, COUNT(*) AS n
            FROM equipment_states
            GROUP BY 1
            ORDER BY n DESC
            """
        )
        report["maintenance_by_type_status"] = grouped(
            """
            SELECT type, status, COUNT(*) AS n
            FROM maintenance_events
            GROUP BY 1, 2
            ORDER BY n DESC
            """
        )
        report["alerts_by_type"] = grouped(
            """
            SELECT alert_type, COUNT(*) AS n
            FROM alerts
            GROUP BY 1
            ORDER BY n DESC
            """
        )
        report["system_events_by_type"] = grouped(
            """
            SELECT event_type, COUNT(*) AS n
            FROM system_events
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 40
            """
        )

        tel_total = report["counts"]["telemetry_rows"]
        missing_sql = """
            SELECT
                COUNT(*) FILTER (WHERE engine_temp_c IS NULL) AS engine_temp_c,
                COUNT(*) FILTER (WHERE coolant_temp_c IS NULL) AS coolant_temp_c,
                COUNT(*) FILTER (WHERE oil_pressure_kpa IS NULL) AS oil_pressure_kpa,
                COUNT(*) FILTER (WHERE engine_rpm IS NULL) AS engine_rpm,
                COUNT(*) FILTER (WHERE engine_load_pct IS NULL) AS engine_load_pct,
                COUNT(*) FILTER (WHERE fuel_rate_lph IS NULL) AS fuel_rate_lph,
                COUNT(*) FILTER (WHERE fuel_level_pct IS NULL) AS fuel_level_pct,
                COUNT(*) FILTER (WHERE battery_voltage IS NULL) AS battery_voltage,
                COUNT(*) FILTER (WHERE speed_kmh IS NULL) AS speed_kmh,
                COUNT(*) FILTER (WHERE payload_t IS NULL) AS payload_t,
                COUNT(*) FILTER (WHERE communication_quality IS NULL) AS communication_quality,
                COUNT(*) FILTER (WHERE engine_hours IS NULL) AS engine_hours,
                COUNT(*) FILTER (WHERE odometer_km IS NULL) AS odometer_km
            FROM equipment_telemetry
        """
        missing_row = dict(session.execute(text(missing_sql)).mappings().one()) if tel_total else {}
        report["telemetry_missing"] = {key: int(value or 0) for key, value in missing_row.items()}
        report["telemetry_missing_rates_pct"] = {
            key: _pct(int(value or 0), tel_total) for key, value in missing_row.items()
        }

        span = session.execute(
            text("SELECT MIN(ts), MAX(ts), COUNT(DISTINCT equipment_id) FROM equipment_telemetry")
        ).one()
        data_start = _aware(span[0])
        data_end = _aware(span[1])
        report["telemetry_span"] = {
            "min_ts": _iso(data_start),
            "max_ts": _iso(data_end),
            "distinct_equipment": int(span[2] or 0),
            "span_minutes": round((data_end - data_start).total_seconds() / 60.0, 1)
            if data_start and data_end
            else None,
        }

        cadence_values = [
            float(v)
            for v in session.execute(
                text(
                    """
                    SELECT delta FROM (
                        SELECT EXTRACT(EPOCH FROM (ts - LAG(ts) OVER (
                            PARTITION BY equipment_id ORDER BY ts
                        ))) AS delta
                        FROM equipment_telemetry
                    ) gaps
                    WHERE delta IS NOT NULL AND delta > 0 AND delta < 3600
                    """
                )
            ).scalars().all()
        ]
        report["telemetry_cadence_seconds"] = _quantiles(cadence_values)

        warn_overlap = dict(
            session.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (
                            WHERE oil_pressure_kpa IS NOT NULL AND oil_pressure_kpa <= 220
                        ) AS oil_warn_or_crit,
                        COUNT(*) FILTER (WHERE oil_pressure_kpa IS NOT NULL) AS oil_n,
                        COUNT(*) FILTER (
                            WHERE engine_temp_c IS NOT NULL AND engine_temp_c >= 98
                        ) AS engine_temp_warn_or_crit,
                        COUNT(*) FILTER (WHERE engine_temp_c IS NOT NULL) AS engine_temp_n,
                        COUNT(*) FILTER (
                            WHERE coolant_temp_c IS NOT NULL AND coolant_temp_c >= 95
                        ) AS coolant_warn_or_crit,
                        COUNT(*) FILTER (WHERE coolant_temp_c IS NOT NULL) AS coolant_n
                    FROM equipment_telemetry
                    """
                )
            ).mappings().one()
        ) if tel_total else {}
        report["healthy_threshold_overlap"] = {
            "oil_warn_or_crit_pct": _pct(int(warn_overlap.get("oil_warn_or_crit") or 0), int(warn_overlap.get("oil_n") or 0)),
            "engine_temp_warn_or_crit_pct": _pct(
                int(warn_overlap.get("engine_temp_warn_or_crit") or 0),
                int(warn_overlap.get("engine_temp_n") or 0),
            ),
            "coolant_warn_or_crit_pct": _pct(
                int(warn_overlap.get("coolant_warn_or_crit") or 0),
                int(warn_overlap.get("coolant_n") or 0),
            ),
            "raw": {key: int(value or 0) for key, value in warn_overlap.items()},
            "note": (
                "Share of ALL telemetry rows already past OEM warn/crit. "
                "Low rates plus high pre-failure rates imply a trivial threshold rule."
            ),
        }

        state_rows = grouped(
            """
            SELECT s.state_id, s.equipment_id, e.code, e.type::text AS equipment_type,
                   s.start_time, s.end_time, s.reason_code, s.reason_text
            FROM equipment_states s
            JOIN equipment e ON e.equipment_id = s.equipment_id
            WHERE s.state = 'STOPPED_MECHANICAL'
            ORDER BY s.equipment_id, s.start_time, s.state_id
            """
        )
        incidents = _merge_mechanical_intervals(state_rows)
        report["incidents"] = {
            "raw_stopped_mechanical_intervals": len(state_rows),
            "merged_incident_count": len(incidents),
            "open_incidents": sum(1 for item in incidents if item["end_time"] is None),
            "per_equipment": [],
            "reason_code_mix": [],
        }
        per_eq: dict[str, int] = defaultdict(int)
        reason_mix: dict[str, int] = defaultdict(int)
        durations_min: list[float] = []
        for item in incidents:
            per_eq[item["code"]] += 1
            codes = item["reason_codes"] or ["NULL"]
            for code in set(codes):
                reason_mix[code or "NULL"] += 1
            if item["end_time"] is not None:
                durations_min.append((item["end_time"] - item["start_time"]).total_seconds() / 60.0)
        report["incidents"]["per_equipment"] = [
            {"code": code, "n": n} for code, n in sorted(per_eq.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        report["incidents"]["reason_code_mix"] = [
            {"reason_code": code, "n": n} for code, n in sorted(reason_mix.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        report["incidents"]["duration_minutes"] = _quantiles(durations_min)
        if incidents:
            starts = sorted(item["start_time"] for item in incidents)
            report["incidents"]["temporal"] = {
                "first_start": _iso(starts[0]),
                "last_start": _iso(starts[-1]),
                "span_minutes": round((starts[-1] - starts[0]).total_seconds() / 60.0, 1),
            }
        else:
            report["incidents"]["temporal"] = {"first_start": None, "last_start": None, "span_minutes": None}

        oem_types = tuple(sorted(EVENT_TYPE_TO_CODE))
        if oem_types:
            oem_stmt = text(
                """
                SELECT equipment_id, ts, event_type
                FROM system_events
                WHERE event_type IN :types
                ORDER BY ts
                """
            ).bindparams(bindparam("types", expanding=True))
            oem_events = [dict(row) for row in session.execute(oem_stmt, {"types": list(oem_types)}).mappings().all()]
        else:
            oem_events = []

        precursor_minutes: list[float] = []
        telemetry_before: dict[int, list[float]] = {h: [] for h in HORIZONS_MIN}
        oem_before_counts: list[int] = []
        oem_after_counts: list[int] = []
        last_sample_warn: list[dict[str, Any]] = []
        excluded = {"no_telemetry_before": 0, "history_shorter_than_5_min": 0}

        for item in incidents:
            lookback = item["start_time"] - timedelta(minutes=MAX_PRECURSOR_MIN)
            rows = grouped(
                """
                SELECT ts, engine_temp_c, coolant_temp_c, oil_pressure_kpa,
                       battery_voltage, fuel_rate_lph, communication_quality
                FROM equipment_telemetry
                WHERE equipment_id = :eid AND ts < :start AND ts >= :lookback
                ORDER BY ts
                """,
                eid=item["equipment_id"],
                start=item["start_time"],
                lookback=lookback,
            )
            if not rows:
                any_before = scalar(
                    """
                    SELECT COUNT(*) FROM equipment_telemetry
                    WHERE equipment_id = :eid AND ts < :start
                    """,
                    eid=item["equipment_id"],
                    start=item["start_time"],
                )
                excluded["no_telemetry_before"] += 1
                if int(any_before or 0) == 0:
                    excluded["history_shorter_than_5_min"] += 1
                continue
            first_ts = _aware(rows[0]["ts"])
            last_ts = _aware(rows[-1]["ts"])
            assert first_ts is not None and last_ts is not None
            precursor_minutes.append((item["start_time"] - first_ts).total_seconds() / 60.0)
            for h in HORIZONS_MIN:
                window_start = item["start_time"] - timedelta(minutes=h)
                n_in_h = sum(1 for row in rows if _aware(row["ts"]) >= window_start)
                telemetry_before[h].append(float(n_in_h))
            oem_before_counts.append(
                sum(
                    1
                    for event in oem_events
                    if event["equipment_id"] == item["equipment_id"]
                    and _aware(event["ts"]) is not None
                    and _aware(event["ts"]) < item["start_time"]
                    and _aware(event["ts"]) >= lookback
                )
            )
            oem_after_counts.append(
                sum(
                    1
                    for event in oem_events
                    if event["equipment_id"] == item["equipment_id"]
                    and _aware(event["ts"]) is not None
                    and _aware(event["ts"]) >= item["start_time"]
                    and (item["end_time"] is None or _aware(event["ts"]) <= item["end_time"])
                )
            )
            last_sample_warn.append(
                {
                    "code": item["code"],
                    "start_time": _iso(item["start_time"]),
                    "minutes_before_last_sample": round(
                        (item["start_time"] - last_ts).total_seconds() / 60.0, 2
                    ),
                    "warn_or_crit_keys": _row_warn_keys(rows[-1]),
                }
            )

        n_incidents = len(incidents)
        last_with_warn = sum(1 for row in last_sample_warn if row["warn_or_crit_keys"])
        report["precursor_coverage"] = {
            "incidents_with_telemetry_in_60min_before": len(precursor_minutes),
            "excluded": excluded,
            "minutes_of_telemetry_before_stop": _quantiles(precursor_minutes),
            "telemetry_rows_in_horizon_before_stop": {
                str(h): _quantiles(telemetry_before[h]) for h in HORIZONS_MIN
            },
            "oem_events_in_60min_before_stop": _quantiles([float(v) for v in oem_before_counts]),
            "oem_events_during_stop": _quantiles([float(v) for v in oem_after_counts]),
            "last_sample_before_stop_warn_or_crit": {
                "n": len(last_sample_warn),
                "n_already_past_threshold": last_with_warn,
                "pct": _pct(last_with_warn, len(last_sample_warn)),
                "samples": last_sample_warn[:20],
            },
        }

        windows: dict[str, Any] = {}
        if data_start and data_end and report["counts"]["equipment"]:
            equipment_ids = [
                int(v)
                for v in session.execute(
                    text("SELECT DISTINCT equipment_id FROM equipment_telemetry ORDER BY 1")
                ).scalars().all()
            ]
            by_eq: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for item in incidents:
                by_eq[item["equipment_id"]].append(item)
            for h in HORIZONS_MIN:
                horizon = timedelta(minutes=h)
                positives = 0
                negatives = 0
                inside_stop = 0
                canonical_usable = 0
                for item in incidents:
                    t0 = item["start_time"] - horizon
                    if t0 >= data_start:
                        canonical_usable += 1
                t = data_start
                last_t = data_end - horizon
                while t <= last_t:
                    for eid in equipment_ids:
                        if _covers(by_eq[eid], eid, t):
                            inside_stop += 1
                            continue
                        if _failure_in_horizon(by_eq[eid], eid, t, horizon):
                            positives += 1
                        else:
                            negatives += 1
                    t = t + NEGATIVE_STRIDE
                ratio = round(positives / negatives, 6) if negatives else None
                windows[str(h)] = {
                    "horizon_min": h,
                    "canonical_incidents_with_room_for_horizon": canonical_usable,
                    "canonical_incidents_missing_horizon": n_incidents - canonical_usable,
                    "stride_positive_windows": positives,
                    "stride_negative_windows": negatives,
                    "stride_windows_inside_an_incident": inside_stop,
                    "positive_negative_ratio": ratio,
                    "imbalance": (
                        "unusable"
                        if n_incidents < 10 or not negatives or (positives / max(negatives, 1) < 0.01 and n_incidents < 20)
                        else "severe"
                        if negatives and positives / negatives < 0.05
                        else "manageable"
                    ),
                }
        else:
            for h in HORIZONS_MIN:
                windows[str(h)] = {
                    "horizon_min": h,
                    "canonical_incidents_with_room_for_horizon": 0,
                    "stride_positive_windows": 0,
                    "stride_negative_windows": 0,
                    "positive_negative_ratio": None,
                    "imbalance": "unusable",
                    "note": "No telemetry time span; cannot build windows.",
                }
        report["window_sampling"] = windows

        few_incidents = n_incidents < 10
        short_precursor = bool(precursor_minutes) and (sum(precursor_minutes) / len(precursor_minutes) < 15)
        no_precursor = n_incidents > 0 and not precursor_minutes
        trivial = (last_with_warn / len(last_sample_warn) >= 0.8) if last_sample_warn else False
        if n_incidents == 0 or few_incidents or short_precursor or no_precursor or trivial:
            verdict = "NOT READY — DATA/SIMULATOR CHANGES REQUIRED"
        else:
            verdict = "READY WITH SMALL DATA FIXES"
        report["readiness_snapshot"] = {
            "verdict": verdict,
            "merged_mechanical_incidents": n_incidents,
            "downtime_events": report["counts"]["downtime_events"],
            "commission_date_populated": report["counts"]["equipment_with_commission_date"] > 0,
            "reasons": {
                "too_few_independent_incidents": few_incidents,
                "mean_precursor_telemetry_under_15_min": short_precursor or no_precursor,
                "last_pre_stop_sample_usually_already_past_oem_threshold": trivial,
                "downtime_events_table_empty": report["counts"]["downtime_events"] == 0,
            },
            "do_not_train": True,
        }

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
