# Causal diagnostic scenarios

MinePulse keeps two simulator fault mechanisms for different jobs:

- Instant injections remain available for UI, alert, resilience, and transport tests.
- Causal scenarios create time-ordered symptoms for diagnostic evaluation. They
  progress from early degradation through measurable symptoms, warning,
  critical condition, and an incident.

The implementation is simulator-only (`simulator/causal_scenarios.py`). Hidden
truth and progression stage stay in simulator memory/developer status. The
engine persists only ordinary telemetry, tyre readings, equipment states,
cycles, alerts, maintenance records, and timestamps. Production operational
services and `app/ai/` never import this layer.

## Existing capability audit

Before this layer, the telemetry and tyre generators already smoothed values,
OEM services already derived threshold events from persisted measurements, and
the engine already persisted state/cycle/queue effects. Manual commands and the
legacy scheduled scenarios, however, apply failures as immediate switches. The
causal manager reuses the gradual generators and persistence path instead of
duplicating them.

## Scenario catalog

| Scenario | Target | Observable progression | Final behavior |
| --- | --- | --- | --- |
| `lubrication_degradation` | haul truck | oil pressure falls, temperature rises, speed derates, OEM threshold event | generic mechanical stop |
| `cooling_degradation` | haul truck | engine/coolant temperature rises, speed derates, OEM threshold event | generic mechanical stop |
| `tyre_degradation` | haul truck | one tyre loses pressure and heats, speed derates, OEM threshold event | safe stop |
| `communication_degradation` | haul truck | link quality falls, intermittent telemetry gaps, connection loss | `NO_DATA`; never mechanical failure |
| `loader_bottleneck` | loader/excavator | loading capacity falls, loading/wait/cycle effects spread across assigned trucks | persistent reduced capacity |

Durations include small seeded variation. Sensor noise remains bounded and
repeatable. The defaults reach an incident in roughly 7–10 simulated minutes,
which is suitable for an accelerated demo.

## Run from the embedded simulator API

Start the backend, reset/start the simulator as usual, then activate a scenario:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/simulation/causal-scenarios/lubrication_degradation/start `
  -ContentType application/json `
  -Body '{"target_id":"TRK-001","duration_min":8,"seed":42}'

Invoke-RestMethod http://127.0.0.1:8000/api/simulation/causal-scenarios
```

Use the returned `run_id` to restore the target without resetting all data:

```powershell
Invoke-RestMethod -Method Delete `
  -Uri http://127.0.0.1:8000/api/simulation/causal-scenarios/<run_id>
```

At 30x simulation speed, an eight-minute scenario takes about 16 wall-clock
seconds. Pause the simulator after the incident, then run the evaluation.

## Prepare evidence from the CLI

From `backend/`:

```powershell
python -m simulator causal-list
python -m simulator causal-run --scenario lubrication_degradation --target TRK-001 --seed 42
python -m simulator causal-run --scenario cooling_degradation --target TRK-002 --seed 42
python -m simulator causal-run --scenario tyre_degradation --target TRK-003 --seed 42
python -m simulator causal-run --scenario communication_degradation --target TRK-004 --seed 42
python -m simulator causal-run --scenario loader_bottleneck --target EXC-001 --seed 42
```

The default CLI run advances quickly and persists the records. Add `--realtime`
to watch the progression in the UI.

## Evaluate persisted evidence

```powershell
python scripts/evaluate_ai.py --case causal_lubrication_degradation
python scripts/evaluate_ai.py --case causal_communication_degradation
python scripts/evaluate_ai.py --case causal_loader_bottleneck
```

These commands use the deterministic provider and cost $0. They validate the
pipeline, evidence provenance, temporal-data availability, and safety mechanics;
they do not evaluate model reasoning quality. Add `--real-llm` only for an
explicit paid Level 3 diagnosis run.

## Truth boundary

Hidden simulator truth includes scenario ID, actual root cause, stage, seed, and
progression parameters. Observable evidence includes only persisted operational
records. Developer simulator endpoints may display hidden truth, but no
operational API, AI contract, graph state, tool, or prompt consumes it.

Results from these scenarios validate behavior against simulated operational
evidence only. They are not proof of production diagnostic accuracy.

