# Synthetic mechanical failure population

MinePulse can optionally enrich a batch simulator run with independent,
progressive mechanical incidents for failure-risk **readiness auditing**. This
does not train, score, or deploy an ML model.

## Architecture and data boundary

The failure-population scheduler and its hidden profile labels live only under
`simulator/`. It activates the existing causal-scenario signal generators and
the normal simulation engine persists only operational observations:

`telemetry -> OEM/system events -> equipment state -> downtime/maintenance`

Production packages (`app/ml`, `app/ai`, and `app/monitoring`) do not import the
simulator. Scenario IDs, hidden causes, seeds, degradation progress, internal
targets, and countdowns are not persisted and must never become features or AI
evidence. The operational target remains the real `STOPPED_MECHANICAL` state
interval detected by the read-only audit.

## Profiles and lifecycle

The seeded population uses a bounded mixture of simulator-only profiles:

- lubrication degradation: falling oil pressure with thermal/performance drift;
- cooling degradation: rising engine and coolant temperatures;
- electrical degradation: falling charging voltage and reduced performance;
- ambiguous mechanical degradation: weaker multivariate drift without a
  guaranteed OEM-threshold crossing.

Default degradation lasts 70–110 simulated minutes. Mechanical downtime lasts
20–50 simulated minutes. At most four incidents progress concurrently, and the
least-used available trucks are preferred to avoid concentrating failures.
Some profiles cross OEM thresholds while ambiguous cases may have no warning.

At an incident, the engine interrupts the active cycle/trip/stage, leaves cycle
duration unavailable, opens a generic unplanned maintenance record and a
mechanical downtime record, and persists `STOPPED_MECHANICAL`. Recovery closes
all three at the same operational timestamp and returns the truck to service.

## Generate and audit

From `backend/`, with the normal PostgreSQL development database available:

```console
python -m simulator.cli generate-cycles --target-cycles 1000 --seed 42 --sim-speed 60 --sample-every-ticks 2 --with-failures
python scripts/audit_failure_risk_dataset.py
```

`--with-failures` is explicit and opt-in. Omitting it preserves the standard
Cycle-Time dataset workflow. Generation resets the simulation site, can take
several minutes because telemetry is persisted through the normal engine, and
prints a developer-only profile/equipment summary at completion.

## Validation levels and limitations

Normal tests use short seeded schedules and cost nothing. PostgreSQL lifecycle
coverage requires:

```console
python -m pytest tests/test_simulator_failure_population.py tests/test_causal_scenarios.py -q --integration
```

The resulting data is synthetic and is not proof of production predictive
accuracy. A readiness verdict still requires independent review of leakage,
window construction, class imbalance, temporal splits, asset-age/reference
fields, and validation against future real FMS/OEM history. Do not train solely
because the simulator audit reports `READY WITH SMALL DATA FIXES`.

## Verified snapshot (seed 42)

The command above was executed after the lifecycle regression tests. It produced
1,047 completed cycles over 2,494 ticks, with 24,940 telemetry rows at a 120-second
cadence. The simulation is paused with no active cycle or incident.

- 70 independent `STOPPED_MECHANICAL` intervals, 70 downtime events, 70 closed
  maintenance events, 70 mechanical alerts, and 70 recovery events;
- 3–4 incidents per truck across all 20 trucks;
- developer-only profile mix: 23 cooling, 18 lubrication, 10 electrical, 19
  ambiguous mechanical incidents;
- observed downtime: 21–50 minutes (mean 37.01 minutes);
- every incident has 59–60 minutes of observed pre-stop telemetry, with no
  missing main telemetry fields;
- 51/70 final pre-stop samples cross an OEM warning/critical threshold (72.9%);
  the other 19 incidents cannot be identified by a universal threshold rule;
- OEM events in the preceding 60 minutes range from 0 to 1 per incident (mean
  0.19); events during stops range from 0 to 1 (mean 0.23).

| Horizon | Samples before each stop | Positive windows | Negative windows | Imbalance |
| --- | ---: | ---: | ---: | --- |
| 15 minutes | 7–8 | 70 | 3,083 | severe |
| 30 minutes | 15 | 140 | 2,994 | severe |
| 60 minutes | 30 | 279 | 2,817 | manageable |

The unchanged read-only audit verdict is **READY WITH SMALL DATA FIXES**. It
still explicitly reports `do_not_train: true`. Asset commissioning dates are
unpopulated, short-horizon imbalance remains severe, and synthetic history is
not field validation. No failure-risk model was trained.

During validation, a lifecycle bug was found: mechanical downtime could start
before a later phase change persisted the mechanical equipment state. The
engine now transitions immediately at the incident timestamp; the final
snapshot has matching counts and the integration test asserts identical
state/downtime start and recovery timestamps.
