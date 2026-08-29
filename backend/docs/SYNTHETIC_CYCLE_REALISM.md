# Synthetic haul-cycle realism

MinePulse's simulator creates plausible prototype operational behaviour. It is
not calibrated to, and does not reproduce, a specific real mine.

## Operational mechanism

Cycle duration is never assigned directly. It emerges from persisted cycle
stages:

`MOVING_EMPTY → WAITING_LOADING → LOADING → MOVING_LOADED → WAITING_DUMPING → DUMPING`

- Catalog haul-road distance, speed limit, grade and quality influence observed
  travel speed and therefore moving-stage duration.
- Each truck has a small seeded persistent travel difference. A larger
  short-lived operating-period variation prevents truck identity from becoming
  a deterministic duration label.
- Each loader has a small persistent service difference and short-lived seeded
  service-rate variation.
- A loader serves one truck at a time. Trucks enter its FIFO queue when arrival
  demand exceeds service capacity; waiting duration therefore emerges from the
  queue rather than from a direct cycle-duration formula.
- Loading and dumping work progresses in simulated seconds. Changing simulator
  acceleration changes wall-clock runtime, not the intended service duration.
- Most hourly operating periods are normal, some are mildly degraded, and a
  small minority create stronger—but still bounded—travel or loading delays.
  Long cycles remain visible through longer persisted moving, waiting, or
  loading stages and through normal telemetry.

The seeded catalog uses driven-road distance rather than straight-line map
distance. `road_quality` is a simulator score from 0 (poor) to 100 (excellent).
Grade and quality are operational catalog attributes, but they remain excluded
from Cycle-Time V1 features.

## Hidden state and production boundaries

Persistent/period runtime factors are simulator implementation details. They
are not written into the cycle-time feature schema, AI evidence, monitoring,
operational APIs, or frontend. Their consequences—speed, state intervals,
queues, stage duration, telemetry, cycles, and production—cross the normal
PostgreSQL boundary.

`app/ml/`, `app/ai/`, and `app/monitoring/` do not import `simulator.*`.

## Reproducibility

Truck, loader, service, and operating-period variation use the configured seed.
The same static world, seed, and tick configuration reproduce equivalent
operations. Different seeds create different plausible operations. Seeded tests
assert relationships and ranges, not brittle exact cycle durations.

## Cycle lifecycle

- `ACTIVE`: currently executing in the live simulator engine.
- `COMPLETED`: dump completed; timestamps and authoritative duration are valid.
- `INTERRUPTED`: the engine stopped/restarted or dataset generation ended before
  completion. The row remains auditable, its target duration stays null, and it
  is excluded from ML training.
- Reset deletes dynamic cycles only for the simulation site. It does not delete
  cycles belonging to future real sites.

Because the runtime world is intentionally in memory, a new engine cannot
safely resume an old cycle. Startup deterministically marks scoped stale ACTIVE
cycles as INTERRUPTED before starting new work. Reset still removes all dynamic
simulation-site cycles for a fresh run.

## Generate and audit a dataset

Stop the API/embedded simulator first so two engines cannot write the simulation
site concurrently. These commands make no LLM calls:

```powershell
cd backend
python -m simulator generate-cycles --target-cycles 1000 --seed 42 --sim-speed 60
python scripts/audit_cycle_time_dataset.py
python -m app.ml.cycle_time.train
```

`generate-cycles` deliberately resets only `MP-SIM-01`, runs without wall-clock
sleeps, persists telemetry every two ticks by default, pauses at the requested
completed-cycle count, and marks the unfinished tail INTERRUPTED. Interactive
simulation continues to persist every tick. The command does not start ML
training.

The read-only audit reports counts, incomplete lifecycle, cycle and stage
distributions, route/loader/truck slices, queue-at-start distribution, and
distance/travel, queue/cycle, and recent-history/next-cycle relationships.

For a quick deterministic smoke run:

```powershell
python -m simulator generate-cycles --target-cycles 50 --seed 42 --max-ticks 3000
```

## Limitations

- Travel uses a kinematic route-progress approximation, not vehicle physics.
- Loader and dump service are capacity/queue abstractions, not shovel-pass or
  crusher discrete-event models.
- Road and equipment parameters are plausible synthetic defaults, not
  field-calibrated distributions.
- Operating-period conditions are bounded stochastic regimes, not weather,
  operator, geology, or dispatch optimization models.
- Payload becomes authoritative during/after loading and dump; Cycle-Time V1
  correctly does not use same-cycle payload at cycle start. A future prediction
  update after loading could use it if the real FMS exposes that timestamp.

Results validate software behaviour against synthetic operational evidence
only. They are not proof of production predictive or diagnostic accuracy.
