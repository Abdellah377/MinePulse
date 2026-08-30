# Failure-risk prediction V1 (prototype)

This model is trained entirely on synthetic MinePulse simulator data and is
intended for prototype validation only. It is **not** field-validated or
production-validated. It is not wired to monitoring, LangGraph, or the frontend.

## What it predicts

At prediction time `T`: probability that this equipment enters a qualifying
`STOPPED_MECHANICAL` incident in the next **60 minutes**, with a **15-minute**
minimum lead-time exclusion used **only when building training windows**.

## Train

From `backend/`:

```
python -m app.ml.failure_risk.train
python -m app.ml.failure_risk.train --eval-only
```

Requires the configured PostgreSQL snapshot. Does not call an LLM or paid API.

## Artifacts

`backend/artifacts/failure_risk/` (gitignored except `.gitkeep`)

- `failure_risk_v1.joblib` — pipelines, baselines, threshold
- `failure_risk_v1.metadata.json` — metrics, split bounds, feature schema, selection

## Windows

- History: rows with `timestamp <= T`, 60-minute lookback
- Stride: 15 minutes
- Exclude active stops, the 15-minute immediate-failure gap (training), and windows with under 15 minutes of history
- Split: chronological incident-grouped 70/15/15; negatives whose horizon crosses a split boundary are dropped

## Features

Telemetry known at `T` (latest / mean / std / slope / change on core sensors),
current operational state, OEM event counts before `T`, and prior maintenance.
`commission_date`, equipment age, tyre telemetry, and simulator hidden fields
are excluded.

## Baselines and models

- Prevalence (train positive rate)
- OEM threshold score from `app.oem.thresholds.classify_value` on latest engine temp, coolant, oil pressure, and battery voltage
- Logistic regression (`class_weight=balanced`)
- HistGradientBoostingClassifier (`class_weight=balanced`)

Selection uses **validation PR-AUC only**. A learned model is served only if it
beats the best baseline by at least 5% relative PR-AUC. HGB is kept over
logistic only with the same 5% bar. The operating threshold **maximizes F1 on
validation**. The test set is never used for selection.

Primary metrics: PR-AUC, ROC-AUC, precision, recall, F1, FP/FN. Accuracy is not primary.

## Inference (internal only)

```
from app.ml.failure_risk.inference import predict_failure_risk
predict_failure_risk(session, equipment_id, prediction_time)
```

Returns `FailureRiskPrediction` with `AVAILABLE` / `UNAVAILABLE` /
`INSUFFICIENT_HISTORY`. Unavailable predictions never report 0% risk.
No HTTP route, monitoring hook, or LangGraph integration in V1.
