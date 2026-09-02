# Automatic operational monitoring V1

Monitoring and investigation deliberately have different jobs:

```text
PostgreSQL operational records
  -> canonical operational/OEM services
  -> Failure-Risk V1 inference (haul trucks, once per site cycle)
  -> monitoring detectors
  -> normal operational alert (RULE or PREDICTION)
  -> STOP

Operator presses Investiguer
  -> app.ai.service.run_investigation
  -> persisted LangGraph result
  -> Alertes IA
```

Monitoring reports an observable symptom and threshold. It never reports a
root cause and never controls equipment, assignments, dispatch, or maintenance.
It also does **not** spend LLM credits when an alert is created. LangGraph
remains the only diagnosis/recommendation layer, and all actions need
human validation.

No detector type auto-starts LangGraph. Failure-Risk scoring stays ML-only.
`MONITORING_AUTO_INVESTIGATE=true` is a legacy opt-in that restores the old
paid auto-investigation path; it is off by default.

## Detectors

| Detector | Canonical input | Default |
| --- | --- | --- |
| Unexpected equipment stop | fleet current state and state timeline | 2 min |
| Prolonged idle/wait | current state interval | 5 min |
| Communication degradation | latest persisted telemetry/state | warning <= 60%, critical <= 30%, stale >= 120 s |
| Critical OEM/maintenance condition | active operational alerts/open maintenance | critical alert or open event |
| Production deviation | published hourly production actual/target rows | 20% below target |
| Abnormal active cycle | active cycle plus authoritative completed-cycle average | 1.5x baseline |
| Predicted mechanical failure risk | served Failure-Risk V1 prediction attached to the snapshot | artifact operating threshold (validation F1 maximizer) |

The predicted-mechanical-failure detector is the first predictive monitor. It
scores only `HAUL_TRUCK` equipment (V1 training is truck telemetry), uses the
probability and threshold copied onto `FailureRiskPrediction`, and never
hard-codes 0.80. A candidate fires only when status is `AVAILABLE` and
`probability >= artifact.threshold`. Fired alerts are always `WARNING`
(`RiskLevel.HIGH` already means the operating threshold was met); `CRITICAL`
remains reserved for confirmed stops and OEM critical alerts. Copy describes
elevated **predicted** risk of a mechanical stop within 60 minutes, not a
confirmed failure. `Alert.predicted_for` stays null: the model does not emit
an occurrence timestamp. The 60-minute window lives on
`metadata.monitoring.horizonMinutes` (and detector copy). Scores below
threshold, `UNAVAILABLE`, and
`INSUFFICIENT_HISTORY` do not create alerts. Metadata labels the source as
`FAILURE_RISK_V1` / `synthetic_prototype`. Scoring runs once per site cycle
inside the existing `monitoring_interval_seconds` loop; a scoring failure
leaves an empty prediction map and the six deterministic detectors continue.

Missing values are not converted to zero. A fresh telemetry record with null
communication quality does not fire a quality detector; measured 0% does.
Production is evaluated only when both actual and target rows are available.
Cycle monitoring is skipped when no completed-cycle baseline exists.

All thresholds are environment settings documented in `.env.example`.
`MONITORING_ENABLED=false` is the safe default. Enabling monitoring creates
deterministic alerts only. Set `MONITORING_AUTO_INVESTIGATE=true` only if you
intentionally want a fired detector to invoke the configured paid provider.

## Deduplication

Each finding has a stable key based on detector and operational scope. The key,
last attempt time, severity, and result ID are stored under `alert.metadata.monitoring`.
An active matching alert is reused. A second investigation is suppressed during
the configured cooldown, unless severity escalates. After cooldown, the same
condition may be investigated again. Existing critical FMS/OEM alerts are linked
instead of copied.

The alert `source_record_id` is `alert-<database id>`, exactly the identifier
already used by Alertes IA to retrieve investigations. Automatic (legacy opt-in)
and manual investigations differ only by `trigger_source`: `AUTOMATIC_MONITORING`
versus `USER_INVESTIGATE`.

## Manual investigation lifecycle

`POST /api/ai/investigations` starts at most one graph run per alert identity
(`site_id` + `source_record_id`). A non-FAILED durable result is reused and
does not spend another provider call. A FAILED result remains in audit history;
**Relancer l’investigation** starts a new investigation id and re-gathers
deterministic evidence with current tools. The previous failure is not returned
as the live result.

Provider HTTP retries: the OpenAI SDK keeps `max_retries=0`. MinePulse retries
only 429, timeout, 5xx, and network errors, up to `AI_PROVIDER_MAX_ATTEMPTS`
(default 3) with exponential backoff and jitter. Invalid API keys, unsupported
models, and structured-output parse errors are not retried.

Concurrency: `AI_INVESTIGATION_MAX_CONCURRENT` (default **2**) is an in-process
semaphore around LangGraph invocation. It prevents a burst of manual starts from
opening 10+ simultaneous LLM requests. Multi-process production would need a
shared lock; this prototype is single-process.

Structured logs include investigation id, alert id, trigger source, attempt
count, failure category, and duration. Prompts, API keys, and chain-of-thought
are not logged.

## Lifecycle and diagnostics

FastAPI starts one idempotent in-process scheduler during lifespan and stops it
cleanly. Each cycle uses its own database session. Site snapshot failures,
individual detector failures, and investigation/provider failures are logged
and isolated so the API and later cycles continue. LangGraph itself never polls.

Inspect candidates without writes or API cost from `backend/`:

```powershell
python scripts/run_monitoring.py --detect-only
```

Run exactly one real cycle (this can call the configured provider):

```powershell
$env:MONITORING_ENABLED="true"
python scripts/run_monitoring.py
```

## Automatic mechanical-breakdown demo

1. Apply migrations and configure one supported AI provider/model/key:

   ```powershell
   cd backend
   python -m alembic upgrade head
   $env:MONITORING_ENABLED="true"
   $env:MONITORING_INTERVAL_SECONDS="10"
   $env:MONITORING_INVESTIGATION_COOLDOWN_MINUTES="15"
   uvicorn app.main:app --reload
   ```

2. Open the frontend in API mode. Reset/start the simulator through the existing
   Simulation Centre. Alerts may appear while you stay on Film / Performance / OEM;
   they must not start LangGraph by themselves. Open **Alertes IA** and press
   **Investiguer** on the chosen alert.
3. Start a reproducible causal breakdown using the existing API:

   ```powershell
   Invoke-RestMethod -Method Post `
     -Uri http://127.0.0.1:8000/api/simulation/inject `
     -ContentType application/json `
     -Body '{"target_type":"EQUIPMENT","target_id":"TRK-001","action":"MECHANICAL_BREAKDOWN","parameters":{"seed":42,"profile":"lubrication"}}'
   ```

4. At the default 30x speed, let the causal progression reach its warning/final
   stop. Monitoring reuses the critical operational alert when available (or
   creates a rule alert). It does not submit an `AUTOMATIC_MONITORING` trigger
   unless `MONITORING_AUTO_INVESTIGATE=true`.
5. Open **Alertes IA**. The alert appears under the normal identifier with
   **Investiguer**. After a manual investigation, the recommendation remains advisory.

To diagnose the data path before spending provider tokens, run
`python scripts/run_monitoring.py --detect-only` after the incident.

## Scope and limitations

This is an in-process prototype scheduler. Multi-process production deployment
would need a single-leader/distributed scheduling mechanism; database-backed
cooldown still limits duplicate investigations but does not replace a strong
distributed lock. Thresholds are deterministic prototype defaults, not mine-
specific certified limits. Production deviation currently uses authoritative
hourly actual/target rows and therefore waits for complete non-null rows.

Neither `app.monitoring` nor `app.ai` imports simulator code. The simulator is
only one source that writes the same persisted operational records a future FMS
or OEM ingestion path will write.

## Simulation reset and clock rules

A reset of `MP-SIM-01` now removes only that site's dynamic operational rows,
FMS alerts, monitoring-generated RULE alerts, automatic investigations, and
manual investigations/recommendations explicitly linked to alerts being
removed. Non-monitoring RULE alerts and records belonging to other sites are
preserved. Predictions are not deleted because the current simulator and
LangGraph V1 do not create them and they have no alert/run link.

Alert timestamps deliberately separate operational truth from persistence
metadata. `Alert.occurred_at` is the authoritative event/detection time used by
the API, UI, ordering, and AI evidence. `Alert.created_at` is the wall-clock UTC
time at which the row was persisted. Legacy rows without `occurred_at` fall back
to `created_at`.

Simulation-mode operational timestamps use the operational clock consistently:

- simulator FMS `Alert.occurred_at` uses simulation time;
- detector `detected_at`, monitoring RULE `Alert.occurred_at`, and LangGraph
  trigger `occurred_at` use the same operational timestamp;
- monitoring cooldown metadata uses operational time so accelerated scenarios
  behave consistently;
- `AiInvestigation.created_at`/`updated_at` remain wall-clock UTC audit metadata.

Reset increments an in-process monitoring generation before deleting data.
Candidates from an older generation cannot write alerts, and an investigation
that finishes after Reset has already committed is deleted as stale. Reset does
not wait for a long provider call and the simulator remains paused afterward.
