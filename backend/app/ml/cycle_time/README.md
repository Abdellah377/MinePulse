# Cycle-time prediction V1 (prototype)

This model is trained entirely on synthetic MinePulse simulator data and is
intended for prototype validation only. It is **not** field-validated or
production-validated.

## Train

From `backend/`:

```
python -m app.ml.cycle_time.train
python -m app.ml.cycle_time.train --eval-only
```

Requires the configured PostgreSQL snapshot. Does not call an LLM.

## Artifacts

`backend/artifacts/cycle_time/` (gitignored except `.gitkeep`)

- `cycle_time_v1.joblib` — preprocessing, HGB, train-only baselines, residual quantiles
- `cycle_time_v1.metadata.json` — metrics, split bounds, feature schema, model status

Recreate with the train command. Do not commit `.joblib` files.

## Target

`total_cycle_duration_minutes = Cycle.total_duration_sec / 60`

Rows used: `status=COMPLETED`, duration present and `> 0`, timestamps present,
and `|duration − (completed_at − started_at)| ≤ 5s`. ACTIVE cycles are never
treated as duration 0.

## Prediction timestamp

`Cycle.started_at`. Every feature is built as-of that instant.

## Features

- truck code, model, capacity
- loader / origin / destination snapshot on the cycle row
- catalog `haul_roads.distance_km` (not `cycles.distance_km`)
- hour of day from `started_at`
- truck / route / loader medians and last-3 truck median from cycles with
  `completed_at < started_at`
- truck×route median only with ≥3 prior completions
- loader waiting-truck count from `equipment_states` overlapping `started_at`

Missing numerics stay null (not zero).

## Explicitly excluded

Same-cycle duration, `completed_at`, same-cycle stage waits, cycle payload,
cycle distance written at dump, post-start alerts/telemetry, `shift_id`,
road grade/quality, simulator `performance_factor` / scenario names.

Historical aggregates never use the test set or later completions. The
temporal split is 70/15/15 by `started_at` with no shuffle. Residual
intervals (10th–90th percentile) are fit on **validation** residuals of the
**served** predictor.

## Baselines vs ML

Train-only global / route / truck medians. HGB is selected on validation MAE
against those baselines. If HGB does not beat the best baseline,
`MODEL_STATUS=BASELINE_NOT_BEATEN` and inference serves that baseline.

## Inference (internal only)

```
from app.ml.cycle_time.inference import predict_cycle_time
predict_cycle_time(session, cycle_id)
```

Returns `CycleTimePrediction` with `AVAILABLE` / `UNAVAILABLE` /
`INSUFFICIENT_HISTORY`. No HTTP route, monitoring hook, or LangGraph
integration in V1.

Empirical bounds are prototype intervals, not calibrated probabilities.
