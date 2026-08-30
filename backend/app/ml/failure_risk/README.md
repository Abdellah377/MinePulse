# Failure-risk prediction V1 (specification only)

This package defines a leakage-safe **STOPPED_MECHANICAL** prediction problem
on synthetic MinePulse data. It does **not** train, score, or deploy a model.

## Target

At prediction time `T`: will this equipment enter a qualifying
`STOPPED_MECHANICAL` incident in the next **60 minutes**?

- Positive: incident start in `(T, T + 60 min]` and `T` is at least **15 minutes** before that start.
- Negative: no qualifying incident starts in that horizon.
- Labels come only from persisted `equipment_states`. Hidden simulator profiles are never the target.

## Windows

- History: rows with timestamp `<= T`, 60-minute lookback.
- Stride: 15 minutes.
- Exclude active incidents, the 15-minute immediate-failure gap, and windows with under 15 minutes of telemetry history.
- Temporal split: chronological **incident-grouped** 70/15/15. Adjacent windows from one incident stay in one split.

## Features

Telemetry known at `T` (latest / rolling / slope / baseline deviation), current operational state, and prior OEM/maintenance counts. `commission_date` / equipment age are **not** V1 features and do not block readiness.

## Audit

```
python scripts/audit_failure_risk_dataset.py
```

Train only when the audit verdict is `READY TO BUILD FAILURE-RISK V1` and `do_not_train` is false. All numbers remain synthetic / prototype.
