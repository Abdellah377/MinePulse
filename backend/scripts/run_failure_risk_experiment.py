#!/usr/bin/env python3
"""Train and evaluate Failure-Risk V1 on a disposable audit database.

Does not read or write the configured MinePulse database. Generation and
training target a uniquely prefixed minepulse_audit_* database that is dropped
in finally. The JSON report and versioned artifacts remain outside that DB.

PROTOTYPE / SYNTHETIC-DATA. This command does not wire models into the UI.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.ml.failure_risk.contracts import MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT, MODEL_VERSION
from app.ml.failure_risk.dataset import load_snapshot
from app.ml.failure_risk.evaluation import relative_pr_auc_improvement
from app.ml.failure_risk.experiment import (
    FEATURE_SET_TEMPORAL,
    FEATURE_SET_V1,
    SplitInvariantError,
    choose_experiment_decision,
    evaluate_all_predictors,
    feature_audit,
    freeze_snapshot,
    permutation_ranks,
    run_validation_experiment,
    save_versioned_artifact,
    score_held_out_test,
    threshold_tradeoffs,
)
from app.ml.failure_risk.features import FEATURE_NAMES, TEMPORAL_EXTRA_FEATURES, FeatureRow, build_feature_rows
from app.ml.failure_risk.model import HGB_DEFAULT_PARAMS, HGB_LIMITED_TUNE, DEFAULT_ARTIFACT_DIR
from app.ml.failure_risk.train import _scores_for, _split_rows, train_from_rows
from app.ml.site_scope import resolve_ml_site_id
from scripts.pre_ml_audit import AuditDatabaseError, resolve_audit_database_url
from scripts.run_pre_ml_multiseed import (
    _admin_url,
    create_database,
    drop_database,
    generate_seed,
    new_audit_database_name,
    run_migrations,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _pr(metrics: dict[str, Any] | None) -> float | None:
    if not metrics:
        return None
    value = metrics.get("pr_auc")
    return None if value is None else float(value)


def _load_frozen(session, *, seed: int, feature_names: tuple[str, ...] = FEATURE_NAMES) -> dict[str, Any]:
    site_id = resolve_ml_site_id(session)
    snapshot = load_snapshot(session, site_id=site_id)
    frozen = freeze_snapshot(snapshot, seed=seed, site_id=site_id, feature_names=feature_names)
    if frozen["do_not_train"]:
        raise RuntimeError(f"Training blocked: {frozen['readiness_verdict']}")
    return frozen


def _ablation_table(rows, *, extra_metadata: dict[str, Any]) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    train, val, _test = _split_rows(rows)
    audit = feature_audit(train + val, feature_names=FEATURE_SET_V1)
    reduced = tuple(
        name for name in FEATURE_SET_V1 if name not in set(audit["near_constant_features"]) or name == "current_state"
    )
    candidates: list[tuple[str, tuple[str, ...]]] = [
        ("v1", FEATURE_SET_V1),
        ("v1_temporal", FEATURE_SET_TEMPORAL),
    ]
    if reduced != FEATURE_SET_V1:
        candidates.append(("v1_drop_constant", reduced))
    results: list[dict[str, Any]] = []
    best_name = "v1"
    best_names = FEATURE_SET_V1
    best_pr = -1.0
    for name, feature_names in candidates:
        _artifact, report = run_validation_experiment(
            rows,
            feature_names=feature_names,
            hgb_param_grid=(HGB_DEFAULT_PARAMS,),
            extra_metadata={**extra_metadata, "feature_set": name},
        )
        hgb_pr = _pr(report.get("hgb_validation"))
        logistic_pr = _pr(report.get("logistic_validation"))
        results.append(
            {
                "feature_set": name,
                "n_features": len(feature_names),
                "hgb_val_pr_auc": hgb_pr,
                "logistic_val_pr_auc": logistic_pr,
                "oem_val_pr_auc": _pr((report.get("baseline_validation") or {}).get("oem_threshold")),
            }
        )
        score = hgb_pr if hgb_pr is not None else -1.0
        if name == "v1":
            best_pr = score
            best_name = name
            best_names = feature_names
            continue
        relative = relative_pr_auc_improvement(best_pr if best_pr > 0 else None, hgb_pr)
        if relative is not None and relative >= MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT and score > best_pr:
            best_pr = score
            best_name = name
            best_names = feature_names
    _ = best_name
    return best_names, results


def _tune_hgb(rows, *, feature_names: tuple[str, ...], extra_metadata: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    default_artifact, default_report = run_validation_experiment(
        rows,
        feature_names=feature_names,
        hgb_param_grid=(HGB_DEFAULT_PARAMS,),
        extra_metadata={**extra_metadata, "stage": "hgb_default"},
    )
    tuned_artifact, tuned_report = run_validation_experiment(
        rows,
        feature_names=feature_names,
        hgb_param_grid=HGB_LIMITED_TUNE,
        extra_metadata={**extra_metadata, "stage": "hgb_limited_tune"},
    )
    default_pr = _pr(default_report.get("hgb_validation"))
    tuned_pr = _pr(tuned_report.get("hgb_validation"))
    relative = relative_pr_auc_improvement(default_pr, tuned_pr)
    if relative is not None and relative >= MIN_ML_RELATIVE_PR_AUC_IMPROVEMENT:
        return dict(tuned_report["hgb_params"]), {
            "default": default_report["hgb_validation"],
            "tuned": tuned_report["hgb_validation"],
            "selected": "tuned",
            "relative_improvement": relative,
            "selected_params": tuned_report["hgb_params"],
        }
    return dict(HGB_DEFAULT_PARAMS), {
        "default": default_report["hgb_validation"],
        "tuned": tuned_report["hgb_validation"],
        "selected": "default",
        "relative_improvement": relative,
        "selected_params": dict(HGB_DEFAULT_PARAMS),
        "reason": "Limited tuning did not beat the default HGB by the 5% relative PR-AUC bar.",
    }


def _robustness_seed(session, *, seed: int, primary_artifact, feature_names: tuple[str, ...], hgb_params: dict[str, Any]) -> dict[str, Any]:
    frozen = _load_frozen(session, seed=seed, feature_names=feature_names)
    rows = frozen["rows"]
    test = [row for row in rows if row.split == "test"]
    transfer = evaluate_all_predictors(
        primary_artifact, test, feature_names=feature_names, threshold=primary_artifact.threshold
    ) if test else {}
    _retrain, retrain_report = train_from_rows(
        rows,
        include_test=True,
        hgb_param_grid=(hgb_params,),
        feature_names=feature_names,
        extra_metadata={"seed": seed, "stage": "robustness_retrain"},
    )
    return {
        "seed": seed,
        "digest": frozen["digest"],
        "n_incidents": frozen["mechanical_incident_count"],
        "readiness_verdict": frozen["readiness_verdict"],
        "transfer_test": {
            name: (payload or {}).get("pr_auc")
            for name, payload in transfer.items()
            if isinstance(payload, dict)
        },
        "retrain_val_pr_auc": {
            "prevalence": _pr((retrain_report.get("baseline_validation") or {}).get("prevalence")),
            "oem_threshold": _pr((retrain_report.get("baseline_validation") or {}).get("oem_threshold")),
            "logistic": _pr(retrain_report.get("logistic_validation")),
            "hgb": _pr(retrain_report.get("hgb_validation")),
        },
        "retrain_test_pr_auc": {
            "logistic": _pr(retrain_report.get("logistic_test")),
            "hgb": _pr(retrain_report.get("hgb_test")),
            "oem_threshold": _pr((retrain_report.get("baseline_test") or {}).get("oem_threshold")),
        },
        "hgb_pr_auc": _pr(retrain_report.get("hgb_validation")),
    }


def _summarize_robustness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hgb_vals = [(item["seed"], item["hgb_pr_auc"]) for item in rows if item.get("hgb_pr_auc") is not None]
    if not hgb_vals:
        return {"seeds": [item["seed"] for item in rows]}
    values = [value for _seed, value in hgb_vals]
    return {
        "seeds": [item["seed"] for item in rows],
        "hgb_val_pr_auc_mean": round(statistics.mean(values), 4),
        "hgb_val_pr_auc_std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "hgb_val_pr_auc_min": {"seed": min(hgb_vals, key=lambda item: item[1])[0], "value": min(values)},
        "hgb_val_pr_auc_max": {"seed": max(hgb_vals, key=lambda item: item[1])[0], "value": max(values)},
        "retrain": rows,
    }


def run_experiment(
    *,
    configured_url: str,
    database_name: str,
    primary_seed: int,
    robustness_seeds: list[int],
    target_cycles: int,
    output: Path,
    artifacts_root: Path,
) -> dict[str, Any]:
    configured = make_url(configured_url)
    audit_url = configured.set(database=database_name)
    explicit = audit_url.render_as_string(hide_password=False)
    resolve_audit_database_url(explicit, configured_url=configured_url)
    admin_url = _admin_url(configured)
    created = False
    engine = None
    try:
        create_database(admin_url, database_name)
        created = True
        run_migrations(audit_url)
        generate_seed(audit_url, seed=primary_seed, target_cycles=target_cycles)
        engine = create_engine(audit_url, future=True, pool_pre_ping=True)
        with Session(engine) as session:
            frozen = _load_frozen(session, seed=primary_seed, feature_names=FEATURE_SET_V1)
            site_id = resolve_ml_site_id(session)
            snapshot = load_snapshot(session, site_id=site_id)
            windows = list(frozen["split"].train) + list(frozen["split"].validation) + list(frozen["split"].test)
            rows_temporal = build_feature_rows(windows, snapshot, feature_names=FEATURE_SET_TEMPORAL)
        rows_v1 = frozen["rows"]
        extra = {"dataset_digest": frozen["digest"], "seed": primary_seed}
        audit = feature_audit(rows_v1, feature_names=FEATURE_SET_V1)
        default_artifact, default_report = run_validation_experiment(
            rows_v1,
            feature_names=FEATURE_SET_V1,
            hgb_param_grid=(HGB_DEFAULT_PARAMS,),
            extra_metadata={**extra, "stage": "hgb_baseline"},
        )
        perm = permutation_ranks(default_artifact, [row for row in rows_v1 if row.split == "validation"])
        chosen_features, ablation = _ablation_table(rows_temporal, extra_metadata=extra)
        working_rows = rows_temporal if chosen_features != FEATURE_SET_V1 else rows_v1
        selected_params, tuning = _tune_hgb(
            working_rows, feature_names=chosen_features, extra_metadata=extra
        )
        final_artifact, selection_report = run_validation_experiment(
            working_rows,
            feature_names=chosen_features,
            hgb_param_grid=(selected_params,),
            extra_metadata={**extra, "stage": "final_selection"},
        )
        val_rows = [row for row in working_rows if row.split == "validation"]
        val_scores = _scores_for(
            final_artifact.served_predictor, final_artifact, val_rows, feature_names=chosen_features
        )
        tradeoffs = threshold_tradeoffs(val_rows, val_scores, selected=final_artifact.threshold)
        test_report = score_held_out_test(
            final_artifact, working_rows, feature_names=chosen_features
        )
        robustness_rows: list[dict[str, Any]] = []
        for seed in robustness_seeds:
            generate_seed(audit_url, seed=seed, target_cycles=target_cycles)
            with Session(engine) as session:
                robustness_rows.append(
                    _robustness_seed(
                        session,
                        seed=seed,
                        primary_artifact=final_artifact,
                        feature_names=chosen_features,
                        hgb_params=selected_params,
                    )
                )
        robustness = _summarize_robustness(robustness_rows)
        decision = choose_experiment_decision(
            served_predictor=final_artifact.served_predictor,
            ml_promoted=bool(selection_report.get("ml_promoted")),
            val_pr_auc={
                "hgb": _pr(selection_report.get("hgb_validation")),
                "logistic": _pr(selection_report.get("logistic_validation")),
                "oem_threshold": _pr((selection_report.get("baseline_validation") or {}).get("oem_threshold")),
            },
            test_pr_auc={
                "hgb": (test_report.get("hgb") or {}).get("pr_auc"),
                "logistic": (test_report.get("logistic") or {}).get("pr_auc"),
            },
            robustness=robustness,
        )
        promote = decision in {"HGB_PROMOTED", "LOGISTIC_PROMOTED", "BASELINE_RETAINED"}
        final_artifact.metadata.update(
            {
                "dataset_digest": frozen["digest"],
                "experiment_seeds": [primary_seed, *robustness_seeds],
                "primary_seed": primary_seed,
                "feature_set": list(chosen_features),
                "hgb_params_final": selected_params,
                "experiment_decision": decision,
                "synthetic_data_warning": selection_report.get("synthetic_data_warning"),
                "training_data_type": "synthetic",
            }
        )
        paths = save_versioned_artifact(
            final_artifact,
            digest=frozen["digest"],
            artifacts_root=artifacts_root,
            promote_canonical=promote,
        )
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prototype": True,
            "training_data_type": "synthetic",
            "audit_database": {"name": database_name, "disposable": True, "dropped_after_run": True},
            "dataset": {
                "digest": frozen["digest"],
                "git_commit": frozen["git_commit"],
                "primary_seed": primary_seed,
                "robustness_seeds": robustness_seeds,
                "target_cycles_per_seed": target_cycles,
                "site_id": frozen["site_id"],
                "equipment_count": frozen["equipment_count"],
                "telemetry_rows": frozen["telemetry_rows"],
                "mechanical_incident_count": frozen["mechanical_incident_count"],
                "positive_windows": frozen["positive_windows"],
                "negative_windows": frozen["negative_windows"],
                "excluded_windows": frozen["excluded_windows"],
                "split": frozen["split_summary"],
                "time_range": {"start": frozen["data_start"], "end": frozen["data_end"]},
                "readiness_verdict": frozen["readiness_verdict"],
                "n_incidents_with_60min_precursor": frozen["n_incidents_with_60min_precursor"],
                "concatenation": "not_used_overlapping_sim_calendars_would_break_temporal_splits",
            },
            "features": {
                "existing": list(FEATURE_SET_V1),
                "temporal_candidates": list(TEMPORAL_EXTRA_FEATURES),
                "selected": list(chosen_features),
                "audit": audit,
                "permutation_importance_hgb_default": perm,
                "ablation": ablation,
            },
            "hgb_baseline_validation": default_report["hgb_validation"],
            "hgb_tuning": tuning,
            "threshold": tradeoffs,
            "validation": {
                "baseline": selection_report.get("baseline_validation"),
                "logistic": selection_report.get("logistic_validation"),
                "hgb": selection_report.get("hgb_validation"),
                "served": selection_report.get("served_validation"),
                "served_operational": selection_report.get("served_validation_operational"),
                "ml_promoted": selection_report.get("ml_promoted"),
                "decision_reason": selection_report.get("decision_reason"),
            },
            "test_once": test_report,
            "robustness": robustness,
            "artifact": paths,
            "decision": decision,
            "ready_for_prototype_integration": decision in {"HGB_PROMOTED", "LOGISTIC_PROMOTED", "BASELINE_RETAINED"},
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return payload
    except SplitInvariantError:
        raise
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            drop_database(admin_url, database_name)


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    parser = argparse.ArgumentParser(description="Run Failure-Risk V1 training on a disposable audit database.")
    parser.add_argument("--primary-seed", type=int, default=42)
    parser.add_argument("--robustness-seed", type=int, action="append", default=None)
    parser.add_argument("--target-cycles", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=BACKEND_ROOT.parent / "reports" / "failure_risk_v1_experiment.json")
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--database-name", default=None)
    args = parser.parse_args(argv)
    robustness = args.robustness_seed if args.robustness_seed else [43, 44, 45, 46]
    database_name = args.database_name or new_audit_database_name(token=f"frv1_{args.primary_seed}")
    payload = run_experiment(
        configured_url=get_settings().database_url,
        database_name=database_name,
        primary_seed=args.primary_seed,
        robustness_seeds=robustness,
        target_cycles=args.target_cycles,
        output=args.output,
        artifacts_root=args.artifacts_dir,
    )
    print(
        json.dumps(
            {
                "report": str(args.output.resolve()),
                "decision": payload["decision"],
                "digest": payload["dataset"]["digest"],
                "audit_database_dropped": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
