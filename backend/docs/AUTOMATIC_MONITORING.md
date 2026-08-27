# Automatic operational monitoring V1

Monitoring and investigation deliberately have different jobs:

```text
PostgreSQL operational records
  -> canonical operational/OEM services
  -> deterministic monitoring detectors
  -> normal operational alert
  -> app.ai.service.run_investigation
  -> persisted LangGraph result
  -> Alertes IA
```

Monitoring reports an observable symptom and threshold. It never reports a
root cause and never controls equipment, assignments, dispatch, or maintenance.
LangGraph remains the only diagnosis/recommendation layer, and all actions need
human validation.

## Detectors

| Detector | Canonical input | Default |
| --- | --- | --- |
| Unexpected equipment stop | fleet current state and state timeline | 2 min |
| Prolonged idle/wait | current state interval | 5 min |
| Communication degradation | latest persisted telemetry/state | warning <= 60%, critical <= 30%, stale >= 120 s |
| Critical OEM/maintenance condition | active operational alerts/open maintenance | critical alert or open event |
| Production deviation | published hourly production actual/target rows | 20% below target |
| Abnormal active cycle | active cycle plus authoritative completed-cycle average | 1.5x baseline |

Missing values are not converted to zero. A fresh telemetry record with null
communication quality does not fire a quality detector; measured 0% does.
Production is evaluated only when both actual and target rows are available.
Cycle monitoring is skipped when no completed-cycle baseline exists.

All thresholds are environment settings documented in `.env.example`.
`MONITORING_ENABLED=false` is the safe default because a fired detector may
invoke the configured paid provider.

## Deduplication

Each finding has a stable key based on detector and operational scope. The key,
last attempt time, severity, and result ID are stored under `alert.metadata.monitoring`.
An active matching alert is reused. A second investigation is suppressed during
the configured cooldown, unless severity escalates. After cooldown, the same
condition may be investigated again. Existing critical FMS/OEM alerts are linked
instead of copied.

The alert `source_record_id` is `alert-<database id>`, exactly the identifier
already used by Alertes IA to retrieve investigations. Automatic and manual
investigations differ only by `trigger_source`: `AUTOMATIC_MONITORING` versus
`USER_INVESTIGATE`.

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
   Simulation Centre, but do not click **Investiguer**.
3. Start a reproducible causal breakdown using the existing API:

   ```powershell
   Invoke-RestMethod -Method Post `
     -Uri http://127.0.0.1:8000/api/simulation/inject `
     -ContentType application/json `
     -Body '{"target_type":"EQUIPMENT","target_id":"TRK-001","action":"MECHANICAL_BREAKDOWN","parameters":{"seed":42,"profile":"lubrication"}}'
   ```

4. At the default 30x speed, let the causal progression reach its warning/final
   stop. Monitoring reuses the critical operational alert when available (or
   creates a rule alert), then submits an `AUTOMATIC_MONITORING` trigger through
   the same investigation service as the manual UI.
5. Open **Alertes IA**. The alert and its persisted result appear under the
   normal alert/investigation identifier. The UI labels the result as automatic;
   the recommendation remains advisory.

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
