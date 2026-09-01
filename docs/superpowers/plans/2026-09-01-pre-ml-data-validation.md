# Pre-ML Data Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct proven simulator/data defects and produce a safe, repeatable multi-seed audit of existing model artifacts.

**Architecture:** Apply small TDD fixes at the simulator and ML data boundaries, then run generation only in a guarded disposable PostgreSQL database. Reuse current dataset builders, baselines, models, and audit contracts; never fit HGB.

**Tech Stack:** Python 3, pytest, SQLAlchemy/PostgreSQL, scikit-learn artifact inference, existing MinePulse simulator.

**Spec:** `docs/superpowers/specs/2026-09-01-pre-ml-data-validation-design.md`

## Global Constraints

- Never write to or reset the configured current MinePulse database.
- Never train, tune, overwrite, or promote HGB.
- Never expose simulator hidden truth to operational rows, production packages, frontend, or ML features.
- Derive expectations from existing simulator configuration and operational contracts; do not invent sensors or mining physics.

---

### Task 1: Simulator lifecycle correctness

**Files:** `backend/tests/test_causal_scenarios.py`, `backend/tests/test_simulator_failure_population.py`, `backend/simulator/apply_commands.py`, `backend/simulator/engine.py`, `backend/simulator/transition_service.py`, `backend/simulator/causal_scenarios.py`

- [ ] Add failing tests for one-shot RESTORE, UI recovery closure, safety-stop persistence/cycle interruption, runtime speed changes, deterministic reset+manual seed, and repeated OEM warning episodes.
- [ ] Run targeted tests and confirm each failure is caused by the audited defect.
- [ ] Implement the smallest lifecycle corrections using existing recovery and transition helpers.
- [ ] Run simulator suites and confirm no hidden metadata reaches persisted payloads.

### Task 2: ML input freshness and site scope

**Files:** `backend/tests/test_ml_failure_risk.py`, `backend/tests/test_ml_cycle_time.py`, `backend/app/ml/failure_risk/{dataset,features,inference}.py`, `backend/app/ml/cycle_time/{dataset,inference}.py`

- [ ] Add failing tests proving empty/stale lookbacks are unavailable, feature timestamp is the latest observed row, and snapshots include one requested site only.
- [ ] Add explicit site filters through equipment/site relations and pass site identity from operational inference callers.
- [ ] Preserve `None`; never impute an unavailable prediction into an operational score.
- [ ] Run both ML unit suites without fitting repository artifacts.

### Task 3: Temporal split and readiness gates

**Files:** `backend/tests/test_ml_failure_risk_spec.py`, `backend/tests/test_ml_cycle_time.py`, `backend/app/ml/failure_risk/spec.py`, `backend/app/ml/failure_risk/train.py`, `backend/app/ml/cycle_time/train.py`

- [ ] Add literal boundary cases proving train end precedes validation start, validation end precedes test start, horizons crossing boundaries are purged, and incident IDs cannot cross partitions.
- [ ] Group equal cycle timestamps so a timestamp cannot appear in multiple partitions.
- [ ] Purge ambiguous failure windows/groups at temporal boundaries and report dropped counts.
- [ ] Make the existing readiness verdict block database training; keep test-only `train_from_rows` available.

### Task 4: Realism contracts and audit harness

**Files:** `backend/tests/test_pre_ml_audit.py`, `backend/scripts/audit_pre_ml_data.py`, `backend/scripts/pre_ml_audit.py`, `backend/docs/PRE_ML_DATA_VALIDATION.md`

- [ ] Test exact audit-DB guard behavior: explicit URL required, database name must start `minepulse_audit_`, and active configured URL is rejected.
- [ ] Test deterministic canonical digests, different-seed variation, bounded sensor/cycle invariants, duplicates, missingness, class reports, label horizons, and hidden-truth exclusion.
- [ ] Implement per-seed generation/report orchestration by reusing simulator and dataset APIs.
- [ ] Evaluate saved artifacts and deterministic baselines only; fail if any code path calls `.fit()` or writes artifacts.
- [ ] Document create/migrate/run/drop commands and destructive-safety behavior.

### Task 5: Isolated execution and final validation

- [ ] Create a uniquely named local database, verify its resolved name and URL differ from the configured database, and migrate it to Alembic head.
- [ ] Run three fixed seeds, save the JSON report, and verify same-seed reproducibility separately.
- [ ] Drop only the exact disposable database after all sessions terminate; retain the JSON report.
- [ ] Run targeted tests, relevant full backend tests, compilation, and final diff review.
- [ ] Report simulator realism, leakage, distributions, per-seed baselines/current-HGB results, limitations, and the readiness verdict.
