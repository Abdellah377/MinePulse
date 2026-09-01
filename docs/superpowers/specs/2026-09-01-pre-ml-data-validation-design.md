# Pre-ML Data Validation Design

## Goal

Determine whether MinePulse's current predictive limitations originate in the simulator/data or in HGB, without fitting or tuning HGB.

## Safety boundaries

- The configured MinePulse database is read-only for audits and must never be reset by the multi-seed runner.
- Mutating generation is allowed only against a separately supplied database whose name starts with `minepulse_audit_`.
- The audit database is migrated independently, contains no production/current-site data, and is safe to drop by exact name after the report is written.
- Simulator hidden truth stays in simulator/evaluator memory. PostgreSQL operational rows, operational services, AI, ML features, monitoring, and product frontend receive observable records only.
- Existing HGB artifacts may be evaluated, but no training, tuning, artifact overwrite, or model promotion is permitted.

## Correctness work before evaluation

1. Repair simulator lifecycle defects that corrupt generated data: one-shot RESTORE commands, causal maintenance/downtime closure, correct safety-stop state/cycle interruption, runtime-speed synchronization, repeatable manual seeds, and OEM warning reset.
2. Reject stale failure-risk inputs and report the actual latest feature timestamp.
3. Scope ML snapshots to one site and make temporal partitions strictly ordered/purged at boundaries.
4. Turn the existing failure-data readiness verdict into a training gate without changing model parameters.
5. Preserve null values and detect invalid sensor/state combinations rather than normalizing them.

## Evaluation architecture

`scripts/audit_pre_ml_data.py` orchestrates a fixed seed list against the isolated database. For each seed it resets only that disposable DB, invokes the existing simulator batch generator with failure population enabled, builds the existing cycle/failure datasets, applies existing baselines and already-saved models without fitting, and writes a JSON report outside the DB.

The report separates simulator/data validity from model quality. Per seed it includes scenario/lifecycle counts, precursor timing, telemetry and cycle distributions, duplicates, missingness, invalid values, constants, label balance, split boundaries/overlap, and baseline-versus-saved-model metrics. Aggregates include mean, median, best/worst seed, and variability. Hidden scenario labels may be used only by simulator/evaluation checks and are never added to operational or ML payloads.

## Verification

Use zero-cost unit tests for all contracts, opt-in PostgreSQL integration tests for persisted isolation/reproducibility, three bounded audit seeds for the manual report, and the existing backend regression suites. The final verdict is `DATA READY FOR MODEL IMPROVEMENT: YES/NO`; a `YES` requires all leakage, temporal, freshness, lifecycle, and reproducibility gates to pass.
