from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_audit_database_url_requires_an_explicit_value():
    from scripts.pre_ml_audit import AuditDatabaseError, resolve_audit_database_url

    with pytest.raises(AuditDatabaseError, match="explicit"):
        resolve_audit_database_url(None, configured_url="postgresql://postgres@localhost/minepulse_db")


def test_audit_database_url_rejects_the_configured_database_even_with_a_different_driver():
    from scripts.pre_ml_audit import AuditDatabaseError, resolve_audit_database_url

    with pytest.raises(AuditDatabaseError, match="configured MinePulse database"):
        resolve_audit_database_url(
            "postgresql+psycopg://audit@localhost:5432/minepulse_audit_configured",
            configured_url="postgresql://postgres@localhost/minepulse_audit_configured",
        )


def test_audit_database_url_requires_the_disposable_name_prefix():
    from scripts.pre_ml_audit import AuditDatabaseError, resolve_audit_database_url

    with pytest.raises(AuditDatabaseError, match="minepulse_audit_"):
        resolve_audit_database_url(
            "postgresql://audit@localhost/minepulse_scratch",
            configured_url="postgresql://postgres@localhost/minepulse_db",
        )


def test_audit_database_url_accepts_a_distinct_prefixed_postgres_database():
    from scripts.pre_ml_audit import resolve_audit_database_url

    resolved = resolve_audit_database_url(
        "postgresql+psycopg://audit:secret@localhost:5432/minepulse_audit_seed_42",
        configured_url="postgresql://postgres@localhost/minepulse_db",
    )

    assert resolved.database == "minepulse_audit_seed_42"
    assert resolved.drivername == "postgresql+psycopg"


def test_canonical_digest_is_key_order_independent_and_seed_sensitive():
    from scripts.pre_ml_audit import canonical_digest

    assert canonical_digest({"seed": 1, "counts": {"telemetry": 3, "cycles": 2}}) == canonical_digest(
        {"counts": {"cycles": 2, "telemetry": 3}, "seed": 1}
    )
    assert canonical_digest({"seed": 1, "counts": {"telemetry": 3}}) != canonical_digest(
        {"seed": 2, "counts": {"telemetry": 3}}
    )


def test_canonical_digest_ignores_its_own_report_field():
    from scripts.pre_ml_audit import canonical_digest

    report = {"seed": 1, "counts": {"telemetry": 3}}
    report["canonical_digest"] = canonical_digest(report)

    assert canonical_digest(report) == report["canonical_digest"]


def test_report_payload_rejects_hidden_truth_keys():
    from scripts.pre_ml_audit import HiddenTruthError, assert_operational_payload

    with pytest.raises(HiddenTruthError, match="scenario"):
        assert_operational_payload({"operational": {"scenario": "secret"}})


def test_report_payload_allows_operational_quality_metrics():
    from scripts.pre_ml_audit import assert_operational_payload

    assert_operational_payload(
        {
            "operational": {"counts": {"telemetry_rows": 4}, "lifecycle": {"open_states": 0}},
            "datasets": {"failure_risk": {"labels": {"positive": 1, "negative": 3}}},
        }
    )


def test_field_quality_reports_missing_constants_and_duplicate_keys():
    from scripts.pre_ml_audit import summarize_rows

    report = summarize_rows(
        [
            {"equipment_id": 1, "ts": "2026-01-01T00:00:00Z", "temperature": 90.0, "rpm": None},
            {"equipment_id": 1, "ts": "2026-01-01T00:00:00Z", "temperature": 90.0, "rpm": 1200.0},
            {"equipment_id": 2, "ts": "2026-01-01T00:01:00Z", "temperature": 90.0, "rpm": 1250.0},
        ],
        duplicate_key=("equipment_id", "ts"),
    )

    assert report["count"] == 3
    assert report["duplicate_rows"] == 1
    assert report["missing"]["rpm"] == 1
    assert report["constant_fields"] == ["temperature"]


def test_telemetry_quality_distinguishes_null_zero_and_impossible_values():
    from scripts.pre_ml_audit import telemetry_value_violations

    report = telemetry_value_violations(
        [
            {"speed_kmh": None, "fuel_level_pct": 0.0, "communication_quality": 90.0},
            {"speed_kmh": -1.0, "fuel_level_pct": 110.0, "communication_quality": None},
        ]
    )

    assert report["outside_physical_bounds"]["speed_kmh"] == 1
    assert report["outside_physical_bounds"]["fuel_level_pct"] == 1
    assert report["measured_zero"]["fuel_level_pct"] == 1
    assert report["null_is_not_zero"] is True


def test_saved_artifact_evaluation_is_read_only_when_artifacts_are_absent():
    from scripts.pre_ml_audit import evaluate_saved_artifacts

    report = evaluate_saved_artifacts([], [], artifacts_root=Path("no_such_audit_artifacts"))

    assert report == {
        "failure_risk": {"status": "artifact_not_found"},
        "cycle_time": {"status": "artifact_not_found"},
    }


def test_saved_artifact_evaluation_reports_empty_test_sets_without_fitting(monkeypatch):
    from app.ml.cycle_time import model as cycle_model
    from app.ml.failure_risk import model as failure_model
    from scripts.pre_ml_audit import evaluate_saved_artifacts

    monkeypatch.setattr(Path, "is_file", lambda self: str(self).endswith(".joblib"))
    monkeypatch.setattr(
        failure_model,
        "load_artifact",
        lambda _path: SimpleNamespace(baselines=object(), threshold=0.5, logistic=None, hgb=None),
    )
    monkeypatch.setattr(
        cycle_model,
        "load_artifact",
        lambda _path: SimpleNamespace(baselines=object(), pipeline=None),
    )

    report = evaluate_saved_artifacts([], [], artifacts_root=Path("existing_artifacts"))

    assert report["failure_risk"]["status"] == "no_evaluation_rows"
    assert report["cycle_time"]["status"] == "no_evaluation_rows"


def test_audit_rejects_an_unsafe_url_before_opening_any_connection(monkeypatch):
    import scripts.pre_ml_audit as audit

    def fail_if_opened(*_args, **_kwargs):
        raise AssertionError("unsafe audit must not open a database connection")

    monkeypatch.setattr(audit, "create_engine", fail_if_opened, raising=False)

    with pytest.raises(audit.AuditDatabaseError):
        audit.audit_database("postgresql://audit@localhost/minepulse_db")


def test_audit_seed_databases_keeps_each_seed_bound_to_its_own_explicit_url(monkeypatch):
    import scripts.pre_ml_audit as audit

    calls: list[tuple[str, int]] = []

    def fake_audit(url, *, seed, artifacts_root=None):
        calls.append((url, seed))
        return {"seed": seed, "url": url}

    monkeypatch.setattr(audit, "audit_database", fake_audit)

    reports = audit.audit_seed_databases(
        {
            11: "postgresql://audit@localhost/minepulse_audit_seed_11",
            7: "postgresql://audit@localhost/minepulse_audit_seed_7",
        }
    )

    assert calls == [
        ("postgresql://audit@localhost/minepulse_audit_seed_7", 7),
        ("postgresql://audit@localhost/minepulse_audit_seed_11", 11),
    ]
    assert [report["seed"] for report in reports] == [7, 11]


def test_audit_cli_emits_one_canonical_report_per_requested_seed(monkeypatch, capsys):
    import scripts.audit_pre_ml_data as cli

    def fake_audit(url, *, seed, artifacts_root=None):
        assert url == "postgresql://audit@localhost/minepulse_audit_case"
        assert artifacts_root is None
        return {"seed": seed, "canonical_digest": f"digest-{seed}"}

    monkeypatch.setattr(cli, "audit_database", fake_audit)

    assert cli.main(
        [
            "--database-url",
            "postgresql://audit@localhost/minepulse_audit_case",
            "--seed",
            "7",
            "--seed",
            "11",
        ]
    ) == 0

    output = capsys.readouterr().out
    assert '"digest-7"' in output
    assert '"digest-11"' in output


def test_audit_cli_supports_distinct_database_urls_per_seed(monkeypatch, capsys):
    import scripts.audit_pre_ml_data as cli

    captured: dict[int, str] = {}

    def fake_many(seed_urls, *, artifacts_root=None):
        captured.update(seed_urls)
        return [{"seed": seed, "canonical_digest": f"digest-{seed}"} for seed in sorted(seed_urls)]

    monkeypatch.setattr(cli, "audit_seed_databases", fake_many)

    assert cli.main(
        [
            "--seed-database",
            "7=postgresql://audit@localhost/minepulse_audit_seed_7",
            "--seed-database",
            "11=postgresql://audit@localhost/minepulse_audit_seed_11",
        ]
    ) == 0

    assert captured == {
        7: "postgresql://audit@localhost/minepulse_audit_seed_7",
        11: "postgresql://audit@localhost/minepulse_audit_seed_11",
    }
    assert '"digest-11"' in capsys.readouterr().out


def test_multi_seed_summary_reports_mean_median_best_and_worst():
    from scripts.pre_ml_audit import summarize_seed_reports

    reports = [
        {
            "seed": 7,
            "datasets": {"cycle_time": {"target_minutes": {"mean": 10.0}}},
            "artifact_evaluation": {
                "cycle_time": {"metrics": {"hgb": {"mae": 3.0}}},
                "failure_risk": {"metrics": {"hgb": {"pr_auc": 0.6}}},
            },
        },
        {
            "seed": 11,
            "datasets": {"cycle_time": {"target_minutes": {"mean": 14.0}}},
            "artifact_evaluation": {
                "cycle_time": {"metrics": {"hgb": {"mae": 5.0}}},
                "failure_risk": {"metrics": {"hgb": {"pr_auc": 0.8}}},
            },
        },
    ]

    summary = summarize_seed_reports(reports)

    assert summary["cycle_target_mean_minutes"] == {
        "count": 2,
        "mean": 12.0,
        "median": 12.0,
        "min": {"seed": 7, "value": 10.0},
        "max": {"seed": 11, "value": 14.0},
    }
    assert summary["cycle_artifacts"]["hgb"]["mae"]["best"] == {
        "seed": 7,
        "value": 3.0,
    }
    assert summary["failure_artifacts"]["hgb"]["pr_auc"]["best"] == {
        "seed": 11,
        "value": 0.8,
    }


def test_managed_audit_database_name_is_prefixed_and_safe():
    from scripts.run_pre_ml_multiseed import new_audit_database_name

    first = new_audit_database_name(token="20260901_a1b2c3")
    second = new_audit_database_name(token="20260901_d4e5f6")

    assert first == "minepulse_audit_20260901_a1b2c3"
    assert second != first


def test_managed_runner_drops_only_the_exact_database_on_failure(monkeypatch, tmp_path):
    import scripts.run_pre_ml_multiseed as runner

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(runner, "create_database", lambda _admin, name: events.append(("create", name)))
    monkeypatch.setattr(runner, "drop_database", lambda _admin, name: events.append(("drop", name)))
    monkeypatch.setattr(runner, "run_migrations", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        runner.run_managed_audit(
            configured_url="postgresql+psycopg://postgres@localhost/minepulse_db",
            database_name="minepulse_audit_test_failure",
            seeds=[7],
            target_cycles=10,
            output=tmp_path / "report.json",
        )

    assert events == [
        ("create", "minepulse_audit_test_failure"),
        ("drop", "minepulse_audit_test_failure"),
    ]


def test_partition_time_range_reports_first_and_last():
    from datetime import datetime, timezone

    from scripts.pre_ml_audit import partition_time_range

    start = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    report = partition_time_range([end, None, start])

    assert report == {"n": 2, "first": start.isoformat(), "last": end.isoformat()}


def test_observable_precursor_examples_use_only_operational_fields():
    from datetime import datetime, timedelta, timezone

    from scripts.pre_ml_audit import assert_operational_payload, observable_precursor_examples

    base = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    snapshot = SimpleNamespace(
        equipment={1: SimpleNamespace(code="TRK-001")},
        telemetry=[
            SimpleNamespace(
                equipment_id=1,
                ts=base - timedelta(minutes=minutes),
                values={
                    "engine_temp_c": 90.0 + minutes / 10.0,
                    "coolant_temp_c": 80.0,
                    "oil_pressure_kpa": 400.0 - minutes,
                    "battery_voltage": 24.0,
                },
            )
            for minutes in (80, 60, 40, 20, 5, 1)
        ],
    )
    incident = SimpleNamespace(equipment_id=1, start_time=base, end_time=base + timedelta(minutes=20))

    examples = observable_precursor_examples(snapshot, [incident], limit=3)

    assert len(examples) == 1
    assert examples[0]["equipment_code"] == "TRK-001"
    assert examples[0]["samples"][0]["minutes_before_stop"] >= examples[0]["samples"][-1]["minutes_before_stop"]
    assert_operational_payload({"operational": {"examples": examples}})


def test_managed_schema_bootstrap_precedes_additive_migrations(monkeypatch):
    import scripts.run_pre_ml_multiseed as runner
    from sqlalchemy.engine import make_url

    events: list[object] = []
    url = make_url("postgresql+psycopg://postgres@localhost/minepulse_audit_test")
    monkeypatch.setattr(runner, "bootstrap_core_schema", lambda value: events.append(("schema", value.database)))
    monkeypatch.setattr(runner, "_run", lambda args, *, audit_url: events.append(("command", args, audit_url.database)))

    runner.run_migrations(url)

    assert events[0] == ("schema", "minepulse_audit_test")
    assert events[1][1][-2:] == ["stamp", runner.SCHEMA_BASELINE_REVISION]
    assert events[2][1][-2:] == ["upgrade", "head"]


def test_sequence_fingerprint_ignores_surrogate_ids_and_saved_artifact_paths():
    from scripts.pre_ml_audit import sequence_fingerprint

    base = {
        "seed": 42,
        "operational": {
            "counts": {"cycles": 10, "telemetry_rows": 20},
            "distributions": {"cycle_status": [{"value": "COMPLETED", "count": 10}]},
            "lifecycle": {"completed_cycles": 10},
            "telemetry": {"duplicate_rows": 0, "missing": {"speed_kmh": 0}},
            "telemetry_value_checks": {"total_outside_physical_bounds": 0},
        },
        "datasets": {
            "failure_risk": {
                "labels": {"positive": 4, "negative": 40},
                "split": {"train": 30, "validation": 7, "test": 7},
                "precursor": {"mechanical_incidents": 12},
            },
            "cycle_time": {
                "target_minutes": {"mean": 18.0},
                "split": {"train": 7, "validation": 2, "test": 1},
            },
        },
        "artifact_evaluation": {"cycle_time": {"artifact": "C:/tmp/a.joblib"}},
        "canonical_digest": "ignore-me",
    }
    replay = {
        **base,
        "artifact_evaluation": {"cycle_time": {"artifact": "D:/other/a.joblib"}},
        "canonical_digest": "different",
        "operational": {
            **base["operational"],
            "cycles": {"duplicate_rows": 0},
        },
    }

    assert sequence_fingerprint(base) == sequence_fingerprint(replay)
    different_seed = {**base, "seed": 43, "datasets": {
        **base["datasets"],
        "failure_risk": {**base["datasets"]["failure_risk"], "labels": {"positive": 9, "negative": 40}},
    }}
    assert sequence_fingerprint(base) != sequence_fingerprint(different_seed)


def test_saved_artifact_alignment_detects_snapshot_mismatch():
    from scripts.pre_ml_audit import saved_artifact_alignment

    report = saved_artifact_alignment(
        {"dataset_sample_count": 12, "split": {"train": {"n": 8}, "validation": {"n": 2}, "test": {"n": 2}}},
        current_sample_count=1400,
        current_split={"train": 980, "validation": 210, "test": 210},
    )

    assert report["matches_current_snapshot"] is False
    assert any(item["field"] == "dataset_sample_count" for item in report["mismatches"])


def test_saved_artifact_alignment_accepts_matching_counts():
    from scripts.pre_ml_audit import saved_artifact_alignment

    report = saved_artifact_alignment(
        {"dataset_sample_count": 100, "split": {"train": {"n": 70}, "validation": {"n": 15}, "test": {"n": 15}}},
        current_sample_count=100,
        current_split={"train": 70, "validation": 15, "test": 15},
    )

    assert report["matches_current_snapshot"] is True
    assert report["mismatches"] == []


def test_managed_audit_replays_the_first_seed_for_sequence_reproducibility(monkeypatch, tmp_path):
    import scripts.run_pre_ml_multiseed as runner

    events: list[tuple[str, object]] = []
    monkeypatch.setattr(runner, "create_database", lambda _admin, name: events.append(("create", name)))
    monkeypatch.setattr(runner, "drop_database", lambda _admin, name: events.append(("drop", name)))
    monkeypatch.setattr(runner, "run_migrations", lambda *_args, **_kwargs: events.append(("migrate", True)))
    monkeypatch.setattr(runner, "generate_seed", lambda _url, *, seed, target_cycles: events.append(("generate", seed)))

    def fake_audit(_url, *, seed, configured_url=None):
        events.append(("audit", seed))
        digest = "same-digest" if seed == 7 else f"digest-{seed}"
        return {
            "seed": seed,
            "canonical_digest": digest,
            "sequence_fingerprint": digest,
            "datasets": {"cycle_time": {"target_minutes": {"mean": 10.0}}},
            "artifact_evaluation": {
                "cycle_time": {"metrics": {"hgb": {"mae": 3.0}}},
                "failure_risk": {"metrics": {"hgb": {"pr_auc": 0.7}}},
            },
        }

    monkeypatch.setattr(runner, "audit_database", fake_audit)

    payload = runner.run_managed_audit(
        configured_url="postgresql+psycopg://postgres@localhost/minepulse_db",
        database_name="minepulse_audit_test_replay",
        seeds=[7, 11],
        target_cycles=10,
        output=tmp_path / "report.json",
    )

    assert [item for item in events if item[0] == "generate"] == [("generate", 7), ("generate", 7), ("generate", 11)]
    assert payload["reproducibility"] == {
        "seed": 7,
        "same_sequence": True,
        "first_fingerprint": "same-digest",
        "replay_fingerprint": "same-digest",
    }
    assert [report["seed"] for report in payload["reports"]] == [7, 11]
