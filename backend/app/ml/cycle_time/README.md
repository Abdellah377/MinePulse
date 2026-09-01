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

For the reproducible synthetic-data workflow and lifecycle semantics, see
[`backend/docs/SYNTHETIC_CYCLE_REALISM.md`](../../../docs/SYNTHETIC_CYCLE_REALISM.md).

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
temporal split is 70/15/15 by `started_at` with no shuffle.

## Served predictor

Cycle-Time V1 is served using a **deterministic hierarchical median**:

`truck median → route median → global median`

That is the official V1 strategy: the simplest predictor that has been reliable
across repeated synthetic seeds. Online inference still adapts to available
truck and route history; it does not hardcode a single constant.

HGB remains an **experimental candidate**. It is always trained, evaluated, and
stored in the artifact so it can be re-checked when richer synthetic data or
real mine data is available. It is **not** the default served predictor.

### Promotion rule (validation only)

HGB may be promoted only when **both** are true:

1. HGB validation MAE is lower than the best deterministic baseline validation MAE
2. Relative MAE improvement is at least `MIN_ML_RELATIVE_MAE_IMPROVEMENT = 0.05` (5%)

```
(best_baseline_mae - hgb_mae) / best_baseline_mae >= 0.05
```

A 2–3% validation-only win does **not** promote HGB. The test set is never used
for model selection; it is reported only.

`MODEL_BEATS_BASELINE` is set only when HGB is actually promoted.
`BASELINE_NOT_BEATEN` covers both an HGB loss and a trivial win below 5%.

All current numbers are synthetic / prototype only. Real mine data may change
the serving decision later.

## Baselines vs ML

Train-only global / route / truck medians plus the hierarchical
`truck_route_global` strategy. HGB is compared on **validation** MAE. Residual
intervals (10th–90th percentile) are fit on **validation** residuals of the
**served** predictor (the hierarchical baseline today; HGB only if promoted).

## Inference (internal only)

```
from app.ml.cycle_time.inference import predict_cycle_time
predict_cycle_time(session, cycle_id, site_id=site_id)
```

Returns `CycleTimePrediction` with `AVAILABLE` / `UNAVAILABLE` /
`INSUFFICIENT_HISTORY`. No HTTP route, monitoring hook, or LangGraph
integration in V1.

Empirical bounds are prototype intervals, not calibrated probabilities.
