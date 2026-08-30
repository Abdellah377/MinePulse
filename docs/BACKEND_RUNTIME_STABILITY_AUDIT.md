# Backend/API runtime stability audit — 2026-08-30

## Verdict

**YES WITH KNOWN LIMITATIONS** for continued local prototype development with
one backend/simulator owner. This is not production or multi-process readiness.
No production model/artifact was tuned or retrained, no AI call was made, and the user's simulation
dataset was not reset. Production frontend components were not changed.

## Runtime map and evidence

- `npm run dev:all` runs Alembic, then one reload-enabled Uvicorn worker and Vite.
- FastAPI lifespan starts the embedded `SimulationService` and optional
  `MonitoringScheduler`. Simulator ticks and lifecycle operations use a service
  lock and one long-lived session. Request dependencies use separate sessions;
  `get_db()` closes them in `finally`. Monitoring opens a session per cycle.
- Operational endpoints resolve `Ctx` before executing route logic:
  `get_operational_context → get_operational_now → SimulationClock → read_control`.
  A control-file failure therefore previously bypassed equipment detail's
  optional inference error boundary and failed the **entire** request.
- `equipment_detail → current_failure_risk → predict_failure_risk` scores current
  persisted data at the operational timestamp. It does not read old alert risk
  metadata. Missing artifact/history/unsupported equipment has typed null output.
- Both main Film and equipment mini-film use
  `useOpsStore.timelineSegments ← full /api/bootstrap ← timeline_for_shift ← equipment_states`.
  Neither uses `/states` as its actual frontend data source. Main Film clips to
  the selected shift's end; the mini-film used the operational current time.
- Bootstrap first loads a lite payload, then a full payload; failures and
  retained old scope/shift selection can affect the visible data. Main Film has
  no independent data-fetch mechanism. It is lazy-loaded and kept mounted.
- Monitoring detectors consume operational snapshots. Reset generation guards
  reject old candidates and remove results finishing after reset. Optional
  prediction errors were logged, but did not restore failed DB transactions.

Recent commits inspected include `641b4a9`, `245ae71`, `4972156`, `e6a169c`,
`fedbbaa`. The current-risk card integration and predictive alert source are
particularly relevant to the reported symptoms.

## Findings and scope decisions

A = confirmed bug; B = strongly evidenced bug; C = architectural risk;
D = expected behavior; E = insufficient reproduction evidence.

| Severity / class | Finding, affected path, evidence | Reproduction | Decision / regression risk |
| --- | --- | --- | --- |
| HIGH / A | `sim_state.json` and `sim_runtime.json` used truncating writes while API threads read them. Equipment context could raise `JSONDecodeError` before the detail route ran. | Supplied traces, code, atomic-publication/concurrent reader tests | MUST FIX: atomic snapshots and explicit unavailable boundary. Low risk; corrupt files are not reset. |
| HIGH / A | Queue append/cancel overlaps tick read/apply/rewrite; a stale rewrite loses new commands or overwrites cancellation. | Both interleavings reproduced by independent tests | MUST FIX: command transaction around complete embedded tick/reset and queue operations. Moderate risk; no multi-process ownership claim. |
| HIGH / B | Tick loaded truck command snapshot before loader/zone processing rewrote statuses. Later truck rewrites could revert those statuses. | Direct execution order in `engine.py` / `apply_commands.py` | MUST FIX: reload after the preceding command phase. No change to command semantics. |
| HIGH / A | Optional predictive failure can leave work/failed PostgreSQL transaction in the caller. | SQLite rollback test, actual PostgreSQL `SELECT 1 / 0` test | MUST FIX: savepoint around optional scoring; caller remains usable. No inference changes. |
| HIGH / A | Reset omitted monitoring `PREDICTION` alerts added by Failure-Risk V1, leaving stale predictions visible. | Isolated PostgreSQL test initially deleted zero matching alerts | MUST FIX: simulation-scoped `PREDICTION` with `monitoring.source=FAILURE_RISK_V1`; existing linked-investigation cleanup reused. |
| HIGH / A | Implicit ORM enum names (`alertsource`, etc.) do not match existing native DB names (`alert_source`, etc.). Psycopg bulk inserts emit invalid casts. | PostgreSQL `UndefinedObject` on bulk alert insert; schema introspection | MUST FIX: canonical enum annotation map on SQLAlchemy Base. No DB migration or value changes. |
| MEDIUM / A | Heartbeat age subtracts simulated January event time from current wall time. | Explicit-clock regression | Small related fix: wall UTC `recorded_at`; legacy age unknown, not fabricated. |
| MEDIUM / A | Historical Film query extends through current operational time instead of selected shift end. | Segment clipping/query-parameter regression | Small related fix: `min(sim_now, shift_window_end)`. Current-shift behavior unchanged. |
| — / E | Reported empty main Film while mini-film is populated. | Fresh browser rendered 197 segments at 1280×720, no initial console errors. Both share bootstrap. | No speculative frontend fix. Historical-window defect is real but **not proven** to explain the original empty screen. Capture failing session's selected shift, full-bootstrap response and console if it recurs. |
| — / D | Failure-Risk card absent after whole detail request fails. | Component clears its fetched score, only assigns it on success. Live truck detail returns AVAILABLE; loader returns UNAVAILABLE/null. | Fix shared request failure, preserve risk semantics. |
| MEDIUM / C | CLI and embedded simulator can own the same DB/runtime directory; each engine boot interrupts/reconciles open work. In-process locks cannot coordinate separate owners. | Startup/CLI/control code | SHOULD FIX SOON before multi-process use: explicit ownership enforcement. For now stop the backend before CLI generation; one Uvicorn worker. |
| MEDIUM / C | Simulator stop joins with a timeout then waits on its lock; cancelling an `asyncio.to_thread` await does not terminate a running monitoring/LLM thread. | Service/scheduler shutdown code | SHOULD FIX SOON: cooperative cancellation/deadlines and ownership-aware shutdown. Not redesigned here. |
| MEDIUM / C | Inference loads complete equipment/telemetry/state/event history for each call, even a single truck request. | `failure_risk.dataset.load_snapshot` | SHOULD FIX SOON before growing datasets: profile and introduce semantically equivalent bounded retrieval. Current inspected request was 0.244 s. Model unchanged. |
| MEDIUM / C | Monitoring metadata uses operational time for attempt cooldown, durable-result lookup uses wall time; missing provider configuration can repeatedly fail and log twice. | `_should_deduplicate`, `_mark_attempt`, nested error logging | SHOULD FIX SOON: explicitly agree cooldown clock/retry policy. No detector threshold or retry semantics changed here. |
| MEDIUM / C | Tick atomic publication is per file, not a transaction across DB/control/runtime; API can see adjacent committed ticks during reset. Bootstrap/lifespan still explicitly consult/boot simulator even with a real clock configured. | Bootstrap, engine, main | Future production decoupling/snapshot consistency work. No claim that real-mode removal of simulator is complete. |
| LOW / C | Event log reads scan entire file before taking last N; checkpoint directory is declared but unused. | Source search | SAFE TO LEAVE FOR LATER: bounded log storage/rotation when measured necessary; no checkpoint redesign. |

## Shared-state contract after fixes

| File | Writers/readers | Protection and missing-data behavior |
| --- | --- | --- |
| `sim_state.json` | Embedded/CLI engine, simulation control routes; operational clock, bootstrap, simulator endpoints | Complete temp in same directory → flush/fsync/close → `os.replace`. In-process read/write lock handles Windows sharing. Merge lock protects control updates. Missing file retains established initial STOPPED control; malformed file or invalid `sim_now` raises an explicit error and is preserved. |
| `sim_runtime.json` | Engine; Simulation Centre diagnostic endpoints | Same atomic helper; missing file is empty diagnostic snapshot, corruption is explicit. Never used as AI/ML evidence. |
| `sim_heartbeat.json` | Engine tick; simulation status | Same atomic helper. `ts` remains operational; new `recorded_at` is wall UTC. Missing or legacy recording timestamp yields null age. |
| `sim_commands.jsonl` | API enqueue/cancel, engine command processing/reset | Atomic complete rewrites plus an in-process transaction across read/apply/write. No append/cancel can interleave with an embedded tick's snapshot. Corrupt lines are not silently discarded. |
| `sim_event_log.jsonl` | Simulator append/reset; API read | Same embedded transaction serializes append/read/reset; reset publishes an empty file atomically. Append is intentionally not an O(history) rewrite. Crash-partial final lines remain an explicit error requiring inspection, not silent truncation. |

Retries are bounded (three attempts, 10 ms gaps), only for filesystem/parse
failures where another writer or Windows handle may be transient. A permanently
corrupt snapshot is not overwritten with a plausible clock. Per-file atomicity
does not permit two simulation engines to operate on the same run.

Clock failures return HTTP 503 with the existing nested error convention:
`detail.code=OPERATIONAL_CLOCK_UNAVAILABLE`; corrupt simulator snapshots use
`SIMULATION_STATE_UNAVAILABLE`. Messages are safe and French; server logs retain
the exception chain. `/health` does not require the clock. RealUtcClock itself
is unchanged and never falls back to simulated or invented time.

Reset still preserves reference configuration, unrelated manual RULE alerts,
unrelated prediction records and other sites. Tagged Failure-Risk alerts are
now included in the existing reset target set; manually linked investigations
and legacy recommendations are cleaned through the existing child-first path.

## Validation

- Added 21 temporary-file tests: atomic publication/failure preservation,
  corrupt-vs-missing behavior, heartbeat clocks, concurrent readers, lost
  append and overwritten cancellation.
- Added 9 runtime tests: native enum names, safe API errors, heartbeat age,
  concurrent reset-style clock publication through the equipment-detail API,
  historical Film bounds, optional-inference rollback, scoped PostgreSQL reset,
  PostgreSQL transaction recovery. Two require `--integration`.
- Added 3 frontend Film tests: main/mini persisted segment agreement, unstarted
  reset window, historical shift filtering. No frontend production edits.
- Existing monitoring test doubles now supply a session/savepoint. Existing
  batch-generation source check follows the new `_tick` body and retains its
  batching assertions; the public `tick` lock is also checked.
- Final `python -m pytest -q`: **325 passed, 26 skipped**. Opt-in DB/real-provider
  tests are skipped by default. Known warnings: Starlette httpx deprecation and
  joblib physical-core discovery fallback on Windows.
- Targeted file/runtime combined run: **28 passed**; subsequently extended
  focused runtime/PostgreSQL run: **9 passed**.
- `npm test`: **97 passed** across 22 files.
- `npx tsc -b`: passed. `npm run build`: passed, existing large map/xlsx chunk warning.
- Python compilation passed. Alembic current is `20260829_ai_debug_trace (head)`;
  no migration added. Canonical enum names match the already-present DB types.
- Existing AST/source-boundary tests still pass for AI/ML/monitoring independence
  and frontend API/mock separation; no null-to-zero coercions or invented exact
  failure timestamps introduced.
- Sandbox initially blocked pytest temp access and Vitest worker spawning;
  successful runs used permitted execution outside that sandbox restriction.

### Runtime checks, not just unit tests

The live persisted bootstrap returned 28 equipment, 197 timeline segments,
`simNow=2026-01-29T08:14:00+00:00`, active `shift-1` (06:00–14:00 UTC).
Main Film displayed those segments in an actual browser. Initial console check
was clean. A later browser reload was blocked by the browser URL policy, so no
post-reload browser verification is claimed.

The original API stopped listening during the audit. Final HTTP checks used a
temporary `uvicorn --lifespan off` process: real persisted data and real local
inference, but no engine boot/ticks, monitoring, or paid provider calls.
`/health`, `/api/bootstrap`, `/api/simulation/status`,
`/api/simulation/equipment`, truck/loader detail, `/api/states`, `/api/cycles`
all returned 200. Twelve concurrent repeated detail/snapshot requests all
returned 200 (maximum 0.777 s in that small run). The truck risk was AVAILABLE
at operational time with a 60-minute horizon; the loader was UNAVAILABLE/null.
This is a smoke check, not a sustained-load benchmark.

The PostgreSQL reset test creates a unique inactive test site and rolls back its
whole transaction. It never calls engine.reset or deletes the current dataset.
An actual live reset/start with causal simulation was **not** performed; tests
cover cleanup and concurrent clock publication separately.

## Repeatable verification

From `backend/`:

```powershell
python -m pytest -q tests/test_runtime_stability.py tests/test_simulator_shared_files.py --integration
python -m pytest -q
python -m compileall -q app simulator tests
python -m alembic current
```

From repository root:

```powershell
npm test
npx tsc -b
npm run build
```

For normal manual reproduction, restart `npm run dev:all` after these changes.
Do not run a standalone simulator concurrently. With a disposable simulation
dataset, pause/reset/start in Simulation Centre while repeatedly opening a truck
detail and Film. Verify current-run alerts only, unchanged reference records,
valid operational timestamps, no 500s, and truthful unavailable risk states.
If preserving the dataset, omit Reset. Inspect `/api/bootstrap` with the **same
site and shift query parameters as the UI** if Film appears empty. Do not use
the capped `/states` list as proof of Film completeness.

Read-only API diagnostic mode (only when port 8000 is free):

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --lifespan off
# In another terminal:
curl.exe http://127.0.0.1:8000/api/bootstrap
curl.exe http://127.0.0.1:8000/api/equipment/TRK-001/detail
```

This mode intentionally does not run monitoring or simulation; stop it before
normal `dev:all`. Do not press simulation mutation controls during read-only
verification (those endpoints can explicitly start the engine).
The temporary diagnostic API process used for this audit was stopped afterward.

## Files changed

Created:

- `backend/simulator/file_io.py`
- `backend/tests/test_simulator_shared_files.py`
- `backend/tests/test_runtime_stability.py`
- `src/pages/supervision/Film.api.test.ts`
- `docs/BACKEND_RUNTIME_STABILITY_AUDIT.md`

Modified:

- `backend/app/api/routes/simulation.py`
- `backend/app/db/database.py`
- `backend/app/main.py`
- `backend/app/monitoring/predictive.py`
- `backend/app/services/operational/clock.py`
- `backend/app/services/operational/timeline.py`
- `backend/app/services/simulator_clock.py`
- `backend/simulator/commands.py`
- `backend/simulator/control.py`
- `backend/simulator/engine.py`
- `backend/simulator/reset_cleanup.py`
- `backend/simulator/world_model.py`
- `backend/tests/test_monitoring_service.py`
- `backend/tests/test_simulator_batch_generation.py`
