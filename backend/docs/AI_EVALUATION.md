# LangGraph V1 evaluation harness

The evaluation harness is development/test tooling under `backend/ai_eval/`.
It invokes the unchanged production path:

`PostgreSQL -> operational/OEM services -> AI evidence tools -> LangGraph -> ai_investigations`

Ground truth is retained only in the evaluation case catalog for scoring. The
production trigger contains ordinary site, shift, equipment, time, and trigger
fields. Scenario names, expected causes, and reviewer notes are rejected by a
runtime isolation assertion before LangGraph is called.

## Case catalog

- `clear_equipment_failure` resolves `EXC-002` and evaluates a persisted breakdown.
- `connectivity_loss` resolves `TRK-004` and evaluates communication/telemetry loss.
- `ambiguous_stop` resolves `TRK-012` and expects an appropriately inconclusive result.
- `causal_lubrication_degradation` evaluates a pre-stop oil-pressure/thermal trend.
- `causal_cooling_degradation` evaluates a pre-stop engine/coolant trend.
- `causal_tyre_degradation` evaluates tyre threshold evidence before a safe stop.
- `causal_communication_degradation` evaluates degraded link quality/gaps without a mechanical claim.
- `causal_loader_bottleneck` evaluates a non-mechanical cross-fleet loading bottleneck.
- `causal_fuel_efficiency_degradation` evaluates a rising fuel-rate trend with
  related performance and cycle evidence.
- `production_operational_bottleneck` rejects a circular shortfall explanation and expects a
  fleet, cycle, loading, waiting, availability, or downtime mechanism.

The equipment codes are setup locators only. The graph receives resolved normal
database IDs and does not know a simulator scenario name.

## Run one case for free

From `backend/` with the database and migrations available:

```bash
python scripts/evaluate_ai.py --case clear_equipment_failure
```

This uses a deterministic mocked provider, but real persisted operational data,
the real tool registry, graph, and durable persistence. It evaluates pipeline
correctness and safety mechanics; it does **not** claim to measure model quality.
Use `--json` for the complete serializable report and `--list` for all cases.

## Opt in to a real provider

```bash
python scripts/evaluate_ai.py --case clear_equipment_failure --real-llm
```

This explicitly invokes `AI_PROVIDER` / `AI_MODEL` and can incur API charges.
One command runs one investigation. Cheap models such as `gpt-4.1-nano` or
`gpt-4o-mini` are suitable for connectivity smoke checks, but a successful run
is not evidence of mining-diagnosis quality.

For pytest, normal runs cost $0. Persisted-data tests opt in with
`pytest tests/test_ai_evaluation_integration.py --integration`. The real-provider
test additionally requires `--run-ai`; it is skipped otherwise.

## Test levels

- Unit evaluation tests use synthetic structured results and deterministic
  providers. They validate scoring, provenance, safety, failure classification,
  data-quality detection, ground-truth isolation, and report serialization.
- Persisted-data integration tests use the current PostgreSQL records, normal
  operational services, production AI tools, LangGraph, and persistence. Their
  provider is mocked unless `--run-ai` is also passed.
- Simulator-driven preparation is optional and outside production AI. If the
  simulator is removed, only its data-preparation/catalog setup needs replacing;
  the evaluator runner and production graph continue to use persisted data.

Reports expose three distinct quality levels:

- `LEVEL_1_INTEGRATION`: did the persisted operational path and graph execute?
- `LEVEL_2_EVIDENCE_REASONING`: did a real model use valid evidence and uncertainty safely?
- `LEVEL_3_ROOT_CAUSE_DIAGNOSIS`: did a real model align with isolated hidden truth using credible temporal evidence?

Mocked-provider runs score Level 1 only. Levels 2 and 3 are reported as
`NOT_SCORED`, even when scripted checks pass. See `CAUSAL_SCENARIOS.md` for data
preparation and demo commands.

RCA scoring also checks symptom restatement, causal depth, temporal support,
valid evidence links, contradiction handling, root-cause confidence, and—for
congestion cases—the availability of bounded shared-loader/queue context. A
PROBABLE or CONFIRMED result must identify a mechanism deeper than the trigger;
otherwise the production graph deterministically downgrades it to INCONCLUSIVE.

The `loading_context` evidence source is built by the operational service from
persisted assignments, equipment-state intervals, cycles, and loading stages.
It is bounded to 6 loaders, 8 waiting trucks per loader, and 8 representative
loading-stage samples per loader. It contains no scenario name or hidden cause.

Reports distinguish provider failures, application/integration failures,
missing operational data, contradictory/data-quality warnings, and reasoning
check failures. No report includes hidden chain-of-thought.
