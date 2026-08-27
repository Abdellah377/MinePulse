# AI telemetry evidence audit

## Finding

The original hypothesis was partially confirmed. Causal scenarios already write
useful timestamped history to PostgreSQL, and MinePulse already had an OEM
history query. Before graph version 1.2, however, equipment investigations sent
only a latest-telemetry timestamp in their initial evidence. Historical values
reached the provider only when the first LLM round explicitly requested
`OEM_DIAGNOSTICS`. A model that did not request that tool never saw the causal
sequence. Requested history was also a raw bucket list without compact
first/last/change/direction summaries.

## Verified path

| Layer | Existing behavior | Audit result |
| --- | --- | --- |
| Simulator persistence | `SimulationEngine._write_telemetry` writes one `equipment_telemetry` row per non-gap tick at simulation time | Timestamped engine/coolant temperature, oil pressure, fuel rate, engine load, speed, payload and communication quality are present |
| Tyres | `_write_tyres` writes `tyre_telemetry` by position and timestamp | Historical tyre values remain available through the OEM tyre service |
| OEM service | `app.oem.queries.get_equipment_signal_history` performs site-scoped bounded history retrieval | Reusable; no new SQL was added to LangGraph or its tools |
| Previous initial AI evidence | Fleet snapshot included `latestTelemetryAt` only | Historical values did not reach the first diagnosis payload |
| Previous requested AI evidence | `OEM_DIAGNOSTICS` metadata included up to 60 history points | History reached the provider only when requested by the LLM |
| Provider boundary | `InvestigationNodes.analyze` serializes all evidence | Any collected history reaches the provider unchanged |

## Graph 1.2 evidence

Equipment-scoped investigations now initially collect
`EQUIPMENT_TELEMETRY_TRENDS`. The same controlled request remains available for
follow-up. Approved groups are `equipment`, `mechanical`, `fuel`, and
`connectivity`; arbitrary SQL and arbitrary signal names remain impossible.

The default incident window is the 15 minutes ending at the trigger timestamp,
clamped to operational now and the active shift. Explicit requests may select a
shorter window, and are capped at 60 minutes. At most eight metrics and eight
representative observed samples per metric enter evidence.

Each metric contains unit, observed window endpoints, first/last/min/max/mean,
absolute and percentage change when valid, direction, sample count, missing-data
status, and timestamped representative observations. No interpolation is used.
Measured zero remains zero; an absent metric remains null with
`insufficient_data`.

## Inspect without an LLM

From `backend/`, after pausing a completed scenario:

```powershell
python scripts/inspect_ai_evidence.py --equipment TRK-001 --group mechanical
python scripts/inspect_ai_evidence.py --equipment TRK-016 --group fuel
```

Use `--incident-time <ISO timestamp>` to pin the incident. Otherwise the command
uses the latest persisted alert for that equipment, falling back to operational
now. The script is read-only, makes no LLM call, and prints the structured trend
evidence used at the provider boundary.

## Safety boundary

Trend evidence contains only persisted operational observations. It never
contains a causal scenario ID, hidden profile, progression stage, or simulator
ground truth. Production `app/ai/` remains simulator-independent.
