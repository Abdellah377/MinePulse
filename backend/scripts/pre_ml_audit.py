"""Safety boundary and read-only helpers for the disposable pre-ML audit.

This module never creates, migrates, drops, resets, trains, or writes an
artifact.  Callers must supply a disposable PostgreSQL URL explicitly.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from collections import Counter
from pathlib import Path
from statistics import mean, median
from datetime import timedelta
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

AUDIT_DATABASE_PREFIX = "minepulse_audit_"
_HIDDEN_TRUTH_TOKENS = frozenset(
    {
        "scenario",
        "scenario_id",
        "causal_scenario",
        "hidden_truth",
        "ground_truth",
        "developer_summary",
    }
)
_PHYSICAL_BOUNDS: dict[str, tuple[float, float]] = {
    "engine_temp_c": (-60.0, 250.0),
    "coolant_temp_c": (-60.0, 200.0),
    "oil_pressure_kpa": (0.0, 2000.0),
    "engine_rpm": (0.0, 10000.0),
    "engine_load_pct": (0.0, 100.0),
    "fuel_rate_lph": (0.0, 1000.0),
    "fuel_level_pct": (0.0, 100.0),
    "battery_voltage": (0.0, 100.0),
    "speed_kmh": (0.0, 200.0),
    "payload_t": (0.0, 1000.0),
    "communication_quality": (0.0, 100.0),
    "engine_hours": (0.0, 1_000_000.0),
    "odometer_km": (0.0, 10_000_000.0),
}


class AuditDatabaseError(ValueError):
    """Raised before an audit can connect to an unsafe database target."""


class HiddenTruthError(ValueError):
    """Raised when a report would expose simulator-only causal metadata."""


def _parse_url(value: str, *, label: str) -> URL:
    try:
        url = make_url(value)
    except Exception as exc:  # SQLAlchemy normalizes its parser exceptions.
        raise AuditDatabaseError(f"{label} must be a valid SQLAlchemy database URL.") from exc
    if not url.drivername.startswith("postgresql"):
        raise AuditDatabaseError(f"{label} must use PostgreSQL.")
    if not url.database:
        raise AuditDatabaseError(f"{label} must include a database name.")
    return url


def _database_target(url: URL) -> tuple[str, str, int, str]:
    """Return the connection target, excluding credentials and driver variant."""
    host = (url.host or "localhost").lower()
    port = int(url.port or 5432)
    return ("postgresql", host, port, str(url.database))


def resolve_audit_database_url(explicit_url: str | None, *, configured_url: str | None = None) -> URL:
    """Validate a caller-supplied disposable database URL before any connection.

    ``configured_url`` is injectable for tests.  In normal execution it is read
    only from the current MinePulse settings after an explicit audit URL exists.
    """
    if not explicit_url or not explicit_url.strip():
        raise AuditDatabaseError("An explicit audit database URL is required.")
    audit_url = _parse_url(explicit_url.strip(), label="Audit database URL")
    if not str(audit_url.database).startswith(AUDIT_DATABASE_PREFIX):
        raise AuditDatabaseError(
            f"Audit database name must start with {AUDIT_DATABASE_PREFIX!r}."
        )
    if configured_url is None:
        from app.config import get_settings

        configured_url = get_settings().database_url
    configured = _parse_url(configured_url, label="Configured MinePulse database URL")
    if _database_target(audit_url) == _database_target(configured):
        raise AuditDatabaseError("Audit database URL targets the configured MinePulse database.")
    return audit_url


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def canonical_digest(report: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 digest for a JSON-compatible report payload."""
    payload = {key: value for key, value in report.items() if key != "canonical_digest"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def sequence_fingerprint(report: Mapping[str, Any]) -> str:
    """Hash simulator/data sequence properties, ignoring surrogate ids and artifact paths.

    PostgreSQL serials such as cycle_id are not reset by DELETE, so a same-seed
    replay can keep identical physics while changing primary keys. Those keys
    must not decide reproducibility.
    """
    operational = report.get("operational") if isinstance(report.get("operational"), Mapping) else {}
    datasets = report.get("datasets") if isinstance(report.get("datasets"), Mapping) else {}
    failure = datasets.get("failure_risk") if isinstance(datasets.get("failure_risk"), Mapping) else {}
    cycle = datasets.get("cycle_time") if isinstance(datasets.get("cycle_time"), Mapping) else {}
    telemetry = operational.get("telemetry") if isinstance(operational.get("telemetry"), Mapping) else {}
    checks = (
        operational.get("telemetry_value_checks")
        if isinstance(operational.get("telemetry_value_checks"), Mapping)
        else {}
    )
    precursor = failure.get("precursor") if isinstance(failure.get("precursor"), Mapping) else {}
    payload = {
        "seed": report.get("seed"),
        "operational": {
            "counts": operational.get("counts"),
            "distributions": operational.get("distributions"),
            "lifecycle": operational.get("lifecycle"),
            "telemetry": {
                "duplicate_rows": telemetry.get("duplicate_rows"),
                "missing": telemetry.get("missing"),
            },
            "telemetry_value_checks": {
                "total_outside_physical_bounds": checks.get("total_outside_physical_bounds"),
            },
        },
        "datasets": {
            "failure_risk": {
                "labels": failure.get("labels"),
                "split": failure.get("split"),
                "precursor": {"mechanical_incidents": precursor.get("mechanical_incidents")},
            },
            "cycle_time": {
                "target_minutes": cycle.get("target_minutes"),
                "split": cycle.get("split"),
            },
        },
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def saved_artifact_alignment(
    metadata: Mapping[str, Any] | None,
    *,
    current_sample_count: int,
    current_split: Mapping[str, int],
) -> dict[str, Any]:
    """Compare saved training metadata with the snapshot currently being audited."""
    metadata = metadata or {}
    mismatches: list[dict[str, Any]] = []
    saved_n = metadata.get("dataset_sample_count")
    if saved_n is not None and int(saved_n) != int(current_sample_count):
        mismatches.append(
            {"field": "dataset_sample_count", "artifact": saved_n, "current": current_sample_count}
        )
    saved_split = metadata.get("split") if isinstance(metadata.get("split"), Mapping) else {}
    for name in ("train", "validation", "test"):
        saved = saved_split.get(name)
        saved_count = saved.get("n") if isinstance(saved, Mapping) else saved
        current = current_split.get(name)
        if saved_count is not None and current is not None and int(saved_count) != int(current):
            mismatches.append(
                {"field": f"split.{name}", "artifact": saved_count, "current": current}
            )
    return {"matches_current_snapshot": not mismatches, "mismatches": mismatches}


def assert_operational_payload(payload: Any, *, path: str = "report") -> None:
    """Reject hidden simulator causality before a report is returned or written."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in _HIDDEN_TRUTH_TOKENS:
                raise HiddenTruthError(f"Hidden simulator truth key {key!r} is forbidden at {path}.")
            assert_operational_payload(value, path=f"{path}.{key}")
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for index, value in enumerate(payload):
            assert_operational_payload(value, path=f"{path}[{index}]")


def summarize_rows(
    rows: Sequence[Mapping[str, Any]], *, duplicate_key: tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Return deterministic missingness, constants, and duplicate diagnostics."""
    fields = sorted({str(key) for row in rows for key in row})
    missing = {field: sum(1 for row in rows if row.get(field) is None) for field in fields}
    constant_fields = [
        field
        for field in fields
        if {repr(row.get(field)) for row in rows if row.get(field) is not None}.__len__() == 1
        and any(row.get(field) is not None for row in rows)
    ]
    duplicates = 0
    if duplicate_key:
        seen: set[tuple[Any, ...]] = set()
        for row in rows:
            key = tuple(row.get(name) for name in duplicate_key)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
    return {
        "count": len(rows),
        "duplicate_rows": duplicates,
        "missing": missing,
        "constant_fields": constant_fields,
    }


def telemetry_value_violations(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Flag physically impossible values without treating observed zero as missing."""
    outside: dict[str, int] = {}
    measured_zero: dict[str, int] = {}
    for metric, (low, high) in _PHYSICAL_BOUNDS.items():
        values = [row.get(metric) for row in rows if row.get(metric) is not None]
        outside[metric] = sum(
            1
            for value in values
            if not isinstance(value, (int, float)) or not low <= float(value) <= high
        )
        measured_zero[metric] = sum(1 for value in values if float(value) == 0.0)
    return {
        "outside_physical_bounds": outside,
        "total_outside_physical_bounds": sum(outside.values()),
        "measured_zero": measured_zero,
        "null_is_not_zero": True,
    }


def evaluate_saved_artifacts(
    failure_rows: list[Any],
    cycle_rows: list[Any],
    *,
    artifacts_root: Path | None = None,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate only already-saved artifacts and their already-fitted baselines.

    No fitting, training, calibration, or artifact persistence occurs here.
    Missing artifacts are reported, rather than silently built.
    """
    from app.ml.cycle_time.evaluation import regression_metrics, targets
    from app.ml.cycle_time.model import ARTIFACT_FILE as CYCLE_ARTIFACT_FILE
    from app.ml.cycle_time.model import DEFAULT_ARTIFACT_DIR as DEFAULT_CYCLE_ARTIFACT_DIR
    from app.ml.cycle_time.model import load_artifact as load_cycle_artifact
    from app.ml.cycle_time.model import predict_pipeline
    from app.ml.failure_risk.evaluation import classification_report, labels_of
    from app.ml.failure_risk.model import ARTIFACT_FILE as FAILURE_ARTIFACT_FILE
    from app.ml.failure_risk.model import DEFAULT_ARTIFACT_DIR as DEFAULT_FAILURE_ARTIFACT_DIR
    from app.ml.failure_risk.model import load_artifact as load_failure_artifact
    from app.ml.failure_risk.model import predict_proba_positive

    failure_path = (artifacts_root / "failure_risk" / FAILURE_ARTIFACT_FILE) if artifacts_root else (
        DEFAULT_FAILURE_ARTIFACT_DIR / FAILURE_ARTIFACT_FILE
    )
    cycle_path = (artifacts_root / "cycle_time" / CYCLE_ARTIFACT_FILE) if artifacts_root else (
        DEFAULT_CYCLE_ARTIFACT_DIR / CYCLE_ARTIFACT_FILE
    )
    report: dict[str, Any] = {}

    def _align(section: dict[str, Any], artifact: Any, kind: str) -> dict[str, Any]:
        if current is None or kind not in current or not isinstance(current[kind], Mapping):
            return section
        spec = current[kind]
        section["snapshot_alignment"] = saved_artifact_alignment(
            getattr(artifact, "metadata", None),
            current_sample_count=int(spec.get("sample_count") or 0),
            current_split=spec.get("split") or {},
        )
        return section

    if not failure_path.is_file():
        report["failure_risk"] = {"status": "artifact_not_found"}
    else:
        artifact = load_failure_artifact(failure_path)
        labeled = [row for row in failure_rows if row.label is not None]
        if not labeled:
            report["failure_risk"] = _align(
                {"status": "no_evaluation_rows", "artifact": str(failure_path), "rows": 0},
                artifact,
                "failure_risk",
            )
        else:
            y_true = labels_of(labeled)
            metrics: dict[str, Any] = {
                "prevalence": classification_report(
                    y_true, artifact.baselines.predict_prevalence(labeled), artifact.threshold
                ),
                "oem_threshold": classification_report(
                    y_true, artifact.baselines.predict_oem_score(labeled), artifact.threshold
                ),
            }
            if artifact.logistic is not None:
                metrics["logistic"] = classification_report(
                    y_true, predict_proba_positive(artifact.logistic, labeled), artifact.threshold
                )
            if artifact.hgb is not None:
                metrics["hgb"] = classification_report(
                    y_true, predict_proba_positive(artifact.hgb, labeled), artifact.threshold
                )
            report["failure_risk"] = _align(
                {
                    "status": "evaluated_saved_artifact",
                    "artifact": str(failure_path),
                    "rows": len(labeled),
                    "metrics": metrics,
                },
                artifact,
                "failure_risk",
            )
    if not cycle_path.is_file():
        report["cycle_time"] = {"status": "artifact_not_found"}
    else:
        artifact = load_cycle_artifact(cycle_path)
        labeled = [row for row in cycle_rows if row.target_minutes is not None]
        if not labeled:
            report["cycle_time"] = _align(
                {"status": "no_evaluation_rows", "artifact": str(cycle_path), "rows": 0},
                artifact,
                "cycle_time",
            )
        else:
            y_true = targets(labeled)
            metrics = {
                "global": regression_metrics(y_true, artifact.baselines.predict_global(labeled)),
                "route": regression_metrics(y_true, artifact.baselines.predict_route(labeled)),
                "truck": regression_metrics(y_true, artifact.baselines.predict_truck(labeled)),
                "truck_route_global": regression_metrics(
                    y_true, artifact.baselines.predict_truck_route_global(labeled)
                ),
            }
            if artifact.pipeline is not None:
                metrics["hgb"] = regression_metrics(y_true, predict_pipeline(artifact.pipeline, labeled))
            report["cycle_time"] = _align(
                {
                    "status": "evaluated_saved_artifact",
                    "artifact": str(cycle_path),
                    "rows": len(labeled),
                    "metrics": metrics,
                },
                artifact,
                "cycle_time",
            )
    return report


def _distribution(values: Sequence[Any]) -> list[dict[str, Any]]:
    counts = Counter(str(value) for value in values)
    return [{"value": value, "count": counts[value]} for value in sorted(counts)]


def _numeric_distribution(values: Sequence[float | None]) -> dict[str, float | int | None]:
    present = [float(value) for value in values if value is not None]
    if not present:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(present),
        "min": round(min(present), 4),
        "max": round(max(present), 4),
        "mean": round(sum(present) / len(present), 4),
    }


def partition_time_range(times: Sequence[Any]) -> dict[str, Any]:
    present = [value for value in times if value is not None]
    if not present:
        return {"n": 0, "first": None, "last": None}
    return {
        "n": len(present),
        "first": min(present).isoformat(),
        "last": max(present).isoformat(),
    }


def observable_precursor_examples(snapshot: Any, incidents: Sequence[Any], *, limit: int = 3) -> list[dict[str, Any]]:
    """Build 2-3 observable telemetry timelines ending at STOPPED_MECHANICAL.

    Uses only operational telemetry fields already present on the ML snapshot.
    """
    examples: list[dict[str, Any]] = []
    ranked = sorted(
        [incident for incident in incidents if getattr(incident, "start_time", None) is not None],
        key=lambda incident: incident.start_time,
    )
    for incident in ranked:
        history = sorted(
            (
                sample
                for sample in snapshot.telemetry
                if sample.equipment_id == incident.equipment_id
                and sample.ts <= incident.start_time
                and sample.ts >= incident.start_time - timedelta(minutes=90)
            ),
            key=lambda sample: sample.ts,
        )
        if len(history) < 4:
            continue
        stride = max(1, len(history) // 4)
        picks = list(history[::stride][:4])
        if picks[-1] is not history[-1]:
            picks.append(history[-1])
        info = snapshot.equipment.get(incident.equipment_id)
        examples.append(
            {
                "equipment_code": getattr(info, "code", None) or incident.equipment_id,
                "stopped_mechanical_at": incident.start_time.isoformat(),
                "telemetry_samples_in_90min": len(history),
                "samples": [
                    {
                        "ts": sample.ts.isoformat(),
                        "minutes_before_stop": round(
                            (incident.start_time - sample.ts).total_seconds() / 60.0, 1
                        ),
                        "engine_temp_c": sample.values.get("engine_temp_c"),
                        "coolant_temp_c": sample.values.get("coolant_temp_c"),
                        "oil_pressure_kpa": sample.values.get("oil_pressure_kpa"),
                        "battery_voltage": sample.values.get("battery_voltage"),
                    }
                    for sample in picks
                ],
            }
        )
        if len(examples) >= limit:
            break
    return examples


def _feature_quality(rows: Sequence[Any], *, id_field: str) -> dict[str, Any]:
    flattened = [{id_field: getattr(row, id_field), **dict(row.values)} for row in rows]
    return {
        "rows": len(rows),
        "missing_rates_pct": {
            key: round(100.0 * value / len(rows), 1) if rows else 0.0
            for key, value in summarize_rows(flattened)["missing"].items()
            if key != id_field
        },
        "constant_fields": [
            key for key in summarize_rows(flattened)["constant_fields"] if key != id_field
        ],
    }


def build_audit_report(session: Session, *, seed: int | None = None, artifacts_root: Path | None = None) -> dict[str, Any]:
    """Build one canonical report using existing read-only dataset builders.

    The report intentionally contains operational observations and ML dataset
    properties only. It does not import simulator scenarios or hidden traces.
    """
    from app.ml.cycle_time.dataset import load_snapshot as load_cycle_snapshot
    from app.ml.cycle_time.dataset import select_training_cycles, snapshot_summary as cycle_snapshot_summary
    from app.ml.cycle_time.features import FEATURE_NAMES as CYCLE_FEATURE_NAMES
    from app.ml.cycle_time.features import FORBIDDEN_FEATURE_NAMES as CYCLE_FORBIDDEN_FEATURE_NAMES
    from app.ml.cycle_time.features import build_feature_rows as build_cycle_feature_rows
    from app.ml.cycle_time.train import temporal_split
    from app.ml.failure_risk.dataset import (
        account_precursor_coverage,
        build_window_split,
        load_snapshot as load_failure_snapshot,
        readiness_evidence,
        snapshot_summary as failure_snapshot_summary,
    )
    from app.ml.failure_risk.features import FEATURE_NAMES as FAILURE_FEATURE_NAMES
    from app.ml.failure_risk.features import missing_rates as failure_missing_rates
    from app.ml.failure_risk.features import build_feature_rows as build_failure_feature_rows
    from app.ml.failure_risk.spec import (
        FORBIDDEN_FEATURE_NAMES as FAILURE_FORBIDDEN_FEATURE_NAMES,
        evaluate_readiness,
        required_telemetry_missing_rate,
        split_has_incident_leakage,
    )
    from app.ml.site_scope import resolve_ml_site_id
    from app.db.models import CycleStage
    from sqlalchemy import select

    site_id = resolve_ml_site_id(session)
    failure_snapshot = load_failure_snapshot(session, site_id=site_id)
    cycle_snapshot = load_cycle_snapshot(session, site_id=site_id)
    telemetry_rows = [
        {"equipment_id": row.equipment_id, "ts": row.ts.isoformat(), **row.values}
        for row in failure_snapshot.telemetry
    ]
    cycle_rows = [
        {
            "cycle_id": row.cycle_id,
            "status": row.status,
            "truck_id": row.truck_id,
            "loader_id": row.loader_id,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "total_duration_sec": row.total_duration_sec,
        }
        for row in cycle_snapshot.cycles
    ]
    state_rows = failure_snapshot.states
    failure_split, failure_exclusions, incidents = build_window_split(failure_snapshot)
    failure_windows = list(failure_split.train) + list(failure_split.validation) + list(failure_split.test)
    failure_features = build_failure_feature_rows(failure_windows, failure_snapshot)
    precursor_coverage = account_precursor_coverage(failure_snapshot, incidents, failure_split)
    training_cycles, cycle_exclusions = select_training_cycles(cycle_snapshot.cycles)
    cycle_features = build_cycle_feature_rows(training_cycles, cycle_snapshot, include_target=True)
    cycle_train, cycle_validation, cycle_test = temporal_split(cycle_features)
    stage_rows = session.scalars(select(CycleStage)).all()
    stage_duration_by_state: dict[str, list[float | None]] = {}
    for stage in stage_rows:
        stage_duration_by_state.setdefault(str(stage.stage.value), []).append(
            float(stage.duration_sec) / 60.0 if stage.duration_sec is not None else None
        )
    state_duration_by_state: dict[str, list[float | None]] = {}
    for state in state_rows:
        duration = (
            (state.end_time - state.start_time).total_seconds() / 60.0
            if state.end_time is not None
            else None
        )
        state_duration_by_state.setdefault(str(state.state), []).append(duration)
    telemetry_distributions = {
        metric: _numeric_distribution([row.get(metric) for row in telemetry_rows])
        for metric in sorted(failure_snapshot.telemetry[0].values)
    } if failure_snapshot.telemetry else {}
    queue_values = [
        row.values.get("loader_waiting_truck_count") for row in cycle_features
    ]
    total_payload = sum(
        float(cycle.payload_t)
        for cycle in cycle_snapshot.cycles
        if cycle.status == "COMPLETED" and cycle.payload_t is not None
    )
    completed_times = [
        value
        for cycle in cycle_snapshot.cycles
        for value in (cycle.started_at, cycle.completed_at)
        if cycle.status == "COMPLETED" and value is not None
    ]
    operational_hours = (
        (max(completed_times) - min(completed_times)).total_seconds() / 3600.0
        if len(completed_times) >= 2
        else 0.0
    )

    report: dict[str, Any] = {
        "seed": seed,
        "operational": {
            "counts": {
                "equipment": len(failure_snapshot.equipment),
                "telemetry_rows": len(telemetry_rows),
                "equipment_state_intervals": len(state_rows),
                "oem_events": len(failure_snapshot.oem_events),
                "maintenance_events": len(failure_snapshot.maintenance),
                "cycles": len(cycle_rows),
            },
            "telemetry": summarize_rows(telemetry_rows, duplicate_key=("equipment_id", "ts")),
            "telemetry_value_checks": telemetry_value_violations(telemetry_rows),
            "cycles": summarize_rows(cycle_rows, duplicate_key=("cycle_id",)),
            "distributions": {
                "equipment_states": _distribution([row.state for row in state_rows]),
                "cycle_status": _distribution([row["status"] for row in cycle_rows]),
                "cycle_duration_min": _numeric_distribution(
                    [
                        float(row["total_duration_sec"]) / 60.0
                        if row["total_duration_sec"] is not None
                        else None
                        for row in cycle_rows
                    ]
                ),
                "cycle_payload_t": _numeric_distribution(
                    [
                        float(cycle.payload_t) if cycle.payload_t is not None else None
                        for cycle in cycle_snapshot.cycles
                        if cycle.status == "COMPLETED"
                    ]
                ),
                "cycle_stage_duration_min": {
                    state: _numeric_distribution(values)
                    for state, values in sorted(stage_duration_by_state.items())
                },
                "equipment_state_duration_min": {
                    state: _numeric_distribution(values)
                    for state, values in sorted(state_duration_by_state.items())
                },
                "loader_queue_at_cycle_start": _numeric_distribution(queue_values),
                "telemetry": telemetry_distributions,
            },
            "throughput_observation": {
                "completed_payload_t": round(total_payload, 2),
                "operational_span_hours": round(operational_hours, 4),
                "tonnes_per_operational_hour": (
                    round(total_payload / operational_hours, 2) if operational_hours > 0 else None
                ),
                "note": "Audit observation only; production business truth remains owned by operational services.",
            },
            "lifecycle": {
                "open_state_intervals": sum(1 for row in state_rows if row.end_time is None),
                "invalid_state_intervals": sum(
                    1
                    for row in state_rows
                    if row.end_time is not None and row.end_time < row.start_time
                ),
                "active_cycles": sum(1 for row in cycle_rows if row["status"] == "ACTIVE"),
                "completed_cycles": sum(1 for row in cycle_rows if row["status"] == "COMPLETED"),
            },
        },
        "datasets": {
            "failure_risk": {
                **failure_snapshot_summary(failure_snapshot, failure_split, failure_exclusions),
                "labels": {
                    "positive": sum(1 for row in failure_features if row.label == 1),
                    "negative": sum(1 for row in failure_features if row.label == 0),
                },
                "split": {
                    "train": len(failure_split.train),
                    "validation": len(failure_split.validation),
                    "test": len(failure_split.test),
                    "dropped_boundary_windows": failure_split.dropped_boundary_windows,
                    "train_time": partition_time_range([row.prediction_time for row in failure_split.train]),
                    "validation_time": partition_time_range(
                        [row.prediction_time for row in failure_split.validation]
                    ),
                    "test_time": partition_time_range([row.prediction_time for row in failure_split.test]),
                },
                "precursor": {
                    "mechanical_incidents": len(incidents),
                    "minutes_to_incident": _numeric_distribution(
                        [row.minutes_to_incident for row in failure_features if row.label == 1]
                    ),
                    "coverage": {
                        "definition": precursor_coverage["definition"],
                        "precursor_coverage_minutes": precursor_coverage["precursor_coverage_minutes"],
                        "counts": precursor_coverage["counts"],
                        "loss_by_reason": precursor_coverage["loss_by_reason"],
                        "flags_by_reason": precursor_coverage["flags_by_reason"],
                        "grid_in_55_to_60": precursor_coverage["grid_in_55_to_60"],
                        "stride_analysis": precursor_coverage["stride_analysis"],
                    },
                    "observable_examples": observable_precursor_examples(failure_snapshot, incidents),
                },
                "quality": _feature_quality(failure_features, id_field="equipment_id"),
            },
            "cycle_time": {
                **cycle_snapshot_summary(cycle_snapshot),
                "excluded": cycle_exclusions,
                "target_minutes": _numeric_distribution([row.target_minutes for row in cycle_features]),
                "split": {
                    "train": len(cycle_train),
                    "validation": len(cycle_validation),
                    "test": len(cycle_test),
                    "train_time": partition_time_range([row.started_at for row in cycle_train]),
                    "validation_time": partition_time_range([row.started_at for row in cycle_validation]),
                    "test_time": partition_time_range([row.started_at for row in cycle_test]),
                },
                "quality": _feature_quality(cycle_features, id_field="cycle_id"),
            },
        },
    }
    failure_rates = failure_missing_rates(failure_features)
    evidence = readiness_evidence(
        failure_snapshot,
        failure_split,
        failure_exclusions,
        incidents,
        missing_rate_max=required_telemetry_missing_rate(failure_rates),
        leakage_feature_violations=len(
            [name for name in FAILURE_FEATURE_NAMES if name in FAILURE_FORBIDDEN_FEATURE_NAMES]
        ),
    )
    readiness = evaluate_readiness(evidence)
    failure_times = [
        [row.prediction_time for row in failure_split.train],
        [row.prediction_time for row in failure_split.validation],
        [row.prediction_time for row in failure_split.test],
    ]
    nonempty_failure_times = [times for times in failure_times if times]
    failure_ordered = all(
        max(left) < min(right)
        for left, right in zip(nonempty_failure_times, nonempty_failure_times[1:])
    )
    cycle_time_sets = [
        {row.started_at for row in cycle_train},
        {row.started_at for row in cycle_validation},
        {row.started_at for row in cycle_test},
    ]
    report["integrity"] = {
        "site_id": site_id,
        "failure_split_incident_leakage": split_has_incident_leakage(failure_split),
        "failure_partitions_strictly_ordered": failure_ordered,
        "cycle_timestamp_overlap": bool(
            cycle_time_sets[0] & cycle_time_sets[1]
            or cycle_time_sets[0] & cycle_time_sets[2]
            or cycle_time_sets[1] & cycle_time_sets[2]
        ),
        "hidden_truth_in_features": {
            "failure_risk": sorted(FAILURE_FORBIDDEN_FEATURE_NAMES.intersection(FAILURE_FEATURE_NAMES)),
            "cycle_time": sorted(CYCLE_FORBIDDEN_FEATURE_NAMES.intersection(CYCLE_FEATURE_NAMES)),
        },
        "readiness": {
            "verdict": readiness.verdict,
            "do_not_train": readiness.do_not_train,
            "n_incidents": evidence.n_incidents,
            "n_incidents_with_60min_precursor": evidence.n_incidents_with_60min_precursor,
            "precursor_coverage": precursor_coverage["counts"],
            "precursor_loss_by_reason": precursor_coverage["loss_by_reason"],
            "precursor_stride_analysis": precursor_coverage["stride_analysis"],
            "n_positive_windows": evidence.n_positive_windows,
            "n_negative_windows": evidence.n_negative_windows,
            "downtime_events": evidence.downtime_events,
            "maintenance_events": evidence.maintenance_events,
            "reasons": readiness.reasons,
            "notes": list(readiness.notes),
        },
    }
    report["artifact_evaluation"] = evaluate_saved_artifacts(
        [row for row in failure_features if row.split == "test"],
        cycle_test,
        artifacts_root=artifacts_root,
        current={
            "failure_risk": {
                "sample_count": len(failure_features),
                "split": {
                    "train": len(failure_split.train),
                    "validation": len(failure_split.validation),
                    "test": len(failure_split.test),
                },
            },
            "cycle_time": {
                "sample_count": len(cycle_features),
                "split": {
                    "train": len(cycle_train),
                    "validation": len(cycle_validation),
                    "test": len(cycle_test),
                },
            },
        },
    )
    report["safety"] = {
        "read_only": True,
        "artifact_writes": False,
        "model_fitting": False,
        "hidden_truth_excluded": True,
        "site_scoped": True,
    }
    assert_operational_payload(report)
    report["sequence_fingerprint"] = sequence_fingerprint(report)
    report["canonical_digest"] = canonical_digest(report)
    return report


def audit_database(
    explicit_url: str | None,
    *,
    seed: int | None = None,
    configured_url: str | None = None,
    artifacts_root: Path | None = None,
) -> dict[str, Any]:
    """Read a validated disposable database and return its audit report."""
    url = resolve_audit_database_url(explicit_url, configured_url=configured_url)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            return build_audit_report(session, seed=seed, artifacts_root=artifacts_root)
    finally:
        engine.dispose()


def audit_seed_databases(
    seed_urls: Mapping[int, str], *, artifacts_root: Path | None = None
) -> list[dict[str, Any]]:
    """Audit independently generated disposable databases in seed order.

    Database lifecycle remains external; every seed retains its own explicit
    URL so no report can silently inspect the configured MinePulse database.
    """
    return [
        audit_database(url, seed=seed, artifacts_root=artifacts_root)
        for seed, url in sorted(seed_urls.items())
    ]


def _seed_stat(points: list[tuple[int, float]], *, higher_is_better: bool | None = None) -> dict[str, Any]:
    ordered = sorted(points, key=lambda item: item[0])
    values = [value for _seed, value in ordered]
    result: dict[str, Any] = {
        "count": len(values),
        "mean": round(mean(values), 4),
        "median": round(median(values), 4),
        "min": {"seed": min(ordered, key=lambda item: item[1])[0], "value": min(values)},
        "max": {"seed": max(ordered, key=lambda item: item[1])[0], "value": max(values)},
    }
    if higher_is_better is not None:
        best = max(ordered, key=lambda item: item[1]) if higher_is_better else min(ordered, key=lambda item: item[1])
        worst = min(ordered, key=lambda item: item[1]) if higher_is_better else max(ordered, key=lambda item: item[1])
        result["best"] = {"seed": best[0], "value": best[1]}
        result["worst"] = {"seed": worst[0], "value": worst[1]}
    return result


def _points(reports: Sequence[Mapping[str, Any]], path: tuple[str, ...]) -> list[tuple[int, float]]:
    result: list[tuple[int, float]] = []
    for report in reports:
        value: Any = report
        for key in path:
            if not isinstance(value, Mapping) or key not in value:
                value = None
                break
            value = value[key]
        seed = report.get("seed")
        if seed is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
            result.append((int(seed), float(value)))
    return result


def summarize_seed_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate comparable per-seed diagnostics without fitting any model."""
    summary: dict[str, Any] = {"seed_count": len(reports)}
    cycle_mean = _points(reports, ("datasets", "cycle_time", "target_minutes", "mean"))
    if cycle_mean:
        summary["cycle_target_mean_minutes"] = _seed_stat(cycle_mean)

    cycle_metrics: dict[str, Any] = {}
    failure_metrics: dict[str, Any] = {}
    for predictor in ("global", "route", "truck", "truck_route_global", "hgb"):
        mae = _points(reports, ("artifact_evaluation", "cycle_time", "metrics", predictor, "mae"))
        if mae:
            cycle_metrics.setdefault(predictor, {})["mae"] = _seed_stat(mae, higher_is_better=False)
    for predictor in ("prevalence", "oem_threshold", "logistic", "hgb"):
        pr_auc = _points(reports, ("artifact_evaluation", "failure_risk", "metrics", predictor, "pr_auc"))
        if pr_auc:
            failure_metrics.setdefault(predictor, {})["pr_auc"] = _seed_stat(
                pr_auc, higher_is_better=True
            )
    summary["cycle_artifacts"] = cycle_metrics
    summary["failure_artifacts"] = failure_metrics
    fingerprints = [
        (int(report["seed"]), str(report.get("sequence_fingerprint")))
        for report in reports
        if report.get("seed") is not None and report.get("sequence_fingerprint")
    ]
    if fingerprints:
        unique = {fingerprint for _seed, fingerprint in fingerprints}
        summary["sequence_fingerprints"] = {
            "unique_count": len(unique),
            "same_across_seeds": len(unique) == 1,
            "by_seed": {str(seed): fingerprint for seed, fingerprint in fingerprints},
        }
    readiness_blocked = [
        int(report["seed"])
        for report in reports
        if report.get("seed") is not None
        and ((report.get("integrity") or {}).get("readiness") or {}).get("do_not_train") is True
    ]
    summary["readiness_do_not_train_seeds"] = readiness_blocked
    precursor_usable = _points(
        reports, ("integrity", "readiness", "precursor_coverage", "usable_precursor_incidents")
    )
    precursor_total = _points(
        reports, ("integrity", "readiness", "precursor_coverage", "total_incidents")
    )
    legacy_ge55 = _points(
        reports, ("integrity", "readiness", "precursor_coverage", "legacy_surviving_labeled_ge_55")
    )
    if precursor_usable and precursor_total:
        summary["precursor_coverage"] = {
            "usable_precursor_incidents": _seed_stat(precursor_usable, higher_is_better=True),
            "total_incidents": _seed_stat(precursor_total, higher_is_better=True),
            "legacy_surviving_labeled_ge_55": _seed_stat(legacy_ge55, higher_is_better=True)
            if legacy_ge55
            else None,
        }
    return summary
