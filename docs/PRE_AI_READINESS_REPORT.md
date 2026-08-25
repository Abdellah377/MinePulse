# Pre-AI Readiness Report

> Historical pre-implementation audit. The bounded V1 investigation graph was
> added on 2026-08-24; the operational source-of-truth findings below remain
> relevant, but statements that LangGraph is "not started" describe the state
> at the time of this audit.

Evidence after closing the independent **NOT READY FOR AI** blockers (A–E). The product is still a **backend-authoritative operational data path** for a future AI optimization layer. LangGraph / LLM / auto-apply remain out of scope.

## Verdict

**NOT READY FOR AI** — there is no agent graph, no LLM tools, and no recommendation orchestration. Human still decides (Préparer / Marquer / Ignorer).

**Data-layer blockers from this audit (A–E) are closed** with code + tests. An independent re-check of items **3, 9, 13, 14, 15, 20** should now PASS on those items. Do not treat this file as a green light to wire LangGraph until a later review confirms the same.

## Failures reproduced, then fixed

| Item | Reproduction | Fix |
|------|----------------|-----|
| **A / 9** | `buildVoyages` used `tripsThisShift * payloadTons`; `buildWaiting` used `count \|\| avg / 10`; `buildDowntime` invented `Ouvert`/`Suivi`; `buildTd`/`buildTu` used `?? 0` | API mode: tons `null`, queue = measured occupancy, status `"—"`, TD/TU average only known values else `"—"` (`src/lib/performance/metrics.ts`) |
| **B / 13** | `useLiveSimulation` cleared `apiPollError` and set `online` after every poll, including equipment-only; Performance Fraîcheur was `formatClock(new Date())` | Equipment-only poll does not clear mutation / incomplete-hydrate errors; `fullWorldHydrated` required for `online` + EN DIRECT; Performance binds Fraîcheur to `lastSuccessfulSyncAt` / `apiPollError` |
| **C / 3** | PATCH ignored response; `actor_label` stored only as `last_actor_label` | `update_alert` persists `assigned_to_label` on ASSIGNED; store applies PATCH DTO; round-trip test PATCH → new session → same status/assignee |
| **D / 14** | Docs presented `alembic upgrade head` as empty-DB install; revision only creates `operational_settings` | Docs state dump + `stamp head` is the only install; upgrade is explicitly **not** a MinePulse schema |
| **E / 15** | Mapper still owned cycle avg fallback (unscoped), downtime, last-500 cycle samples; frontend recomputed attainment | `cycles.*`, `downtime.downtime_reasons` are shift-scoped services; bootstrap/production routes call services; `shiftProductionRollup` displays backend fields only |

## Residuals closed in the same pass

- Cycle-time samples are shift-scoped via `OperationalContext` (not last 500 unscoped).
- Bootstrap operators come from site equipment assignments (plus alert assignees), not `limit(20)` global; alerts filtered by site equipment/zones.
- OEM connectivity / delays / ping filter `Equipment.site_id`; `parse_range` uses operational context.
- `WATER_TRUCK` / `LIGHT_VEHICLE` / `OTHER` map to truthful UI types (not `haul_truck`); voyage KPIs stay haul-truck-only.
- Shift DTO includes `startMinute` / `endMinute`; `shiftWindowBounds` uses them.

## Checklist

| Area | Status | Evidence |
|------|--------|----------|
| TypeScript (`npx tsc -b`) | **PASS** | exit 0 |
| vitest (`npx vitest run`) | **PASS** | 8 files, 30 tests (metrics API, apiSync, mergeProduction, shiftWindow) |
| Backend compile | **PASS** | `python -m compileall app simulator -q` |
| pytest (`python -m pytest tests/ -q`) | **PASS** | 22 passed, 2 skipped (`--integration` HTTP tests) |
| Static audit | **PASS** | `audit_static_data.py` → 0 INVALID |
| Schema verify (local Postgres) | **PASS** | 25/25 expected tables |
| Alert assignee round-trip (local Postgres) | **PASS** | `test_alert_patch_assignee_survives_new_session`; row deleted in `finally` |
| Performance API mode | **PASS** | no invented tons / queue / downtime status / 0% TD-TU |
| Live poll honesty | **PASS** | equipment-only success cannot clear sticky errors or mark a lite world EN DIRECT |
| Alembic story | **PASS** | dump + stamp; upgrade is not a full schema |

## Commands (this pass)

```bash
npx tsc -b
npx vitest run
cd backend
python -m compileall app simulator -q
python -m pytest tests/ -q
python scripts/verify_schema.py
python -m pytest tests/test_alerts.py -v
cd ..
python backend/scripts/audit_static_data.py
```

Observed:

- `tsc -b` — exit 0
- `vitest run` — 30 passed
- `pytest tests/ -q` — `22 passed, 2 skipped`
- `verify_schema.py` — Expected tables: 25 \| Found: 25
- `test_alert_patch_assignee_survives_new_session` — PASSED
- `audit_static_data.py` — INVALID_OPERATIONAL_HARDCODE: 0

Skipped (need `pytest --integration` + live API): `test_bootstrap_lite_omits_production`, `test_equipment_detail_contract`.

## What still fails / is out of scope

- LangGraph agent graph, LLM tools, RAG, auto-apply — **not started**. This is why the verdict stays **NOT READY FOR AI**.
- OEM diagnostic / errors / telemetry / tyre routes still resolve equipment by code without a required site filter (connectivity family is site-scoped).
- Mapper still has a non-bulk `_wait_idle_minutes` path; live/bootstrap use `FleetBulkContext`.
- Mock mode (`VITE_USE_API=false`) may still hardcode the Merah scenario — allowed, and still classified by the audit script.

## Next step for AI

Wire LangGraph tools **only** to `app/services/operational/*` (`production_summary`, `downtime_reasons`, `cycle_time_samples`, `avg_cycle_minutes_*`, `update_alert`, `list_site_alerts`, …). Screens remain sensors. Human actions remain Préparer / Marquer / Ignorer.
