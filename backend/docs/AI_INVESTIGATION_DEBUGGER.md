# Developer-only AI investigation debugger

The debugger is an observability layer around the existing LangGraph investigation.
It does **not** change prompts, diagnosis gates, evidence selection, monitoring, or
the simulator. Operators still see `InvestigationResult` only.

## Enable

1. Set `AI_DEBUG_MODE=true` in `.env` (same opt-in pattern as `MONITORING_ENABLED`).
2. Restart the API process so `get_settings()` reloads.
3. Run `python -m alembic upgrade head` from `backend/` so `ai_investigations.debug_trace` exists.
4. Start an investigation from Alertes IA.
5. Open Alertes IA and expand **Trace technique (dev)** at the bottom of the main investigation column.

There is no `VITE_` flag. The frontend shows the panel only when
`GET /api/ai/investigations/{id}/debug` returns 200. A 403 (`AI_DEBUG_DISABLED`)
or 404 hides it entirely.

## What is stored

A bounded JSON document on the investigation row (`debug_trace` JSONB):

| Layer | What you see |
| --- | --- |
| Evidence | Tool names, IDs, availability, ≤400 character previews. Not full payloads. |
| Structured LLM output | Compact diagnosis/conclusion snapshots (`can_conclude`, confidence, hypothesis IDs). |
| Deterministic validation | Gate checks such as `DIAGNOSIS_CANNOT_CONCLUDE` and `CAUSAL_DEPTH_TOO_LOW`. |
| Debug trace | Ordered wall-clock events, stop reason, coverage, optional token usage. |
| Hidden chain-of-thought | **Not stored.** `reasoning_summary`, prompts, headers, and API keys are dropped. |

Simulation Reset already deletes matching `AiInvestigation` rows, so traces go with them.

## Current RCA (documented, not changed)

`_sanitize_conclusion` still requires `diagnosis.can_conclude` for `probable_eligible`,
and hypotheses with `causal_depth < 1` are excluded. That combination is a likely
reason many investigations collapse to `INCONCLUSIVE`. The debugger surfaces those
gates; it does not retune them.
