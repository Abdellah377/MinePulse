# Alertes IA / Actions IA corrective pass — 2026-08-26

## Reproduced failure and correction

The actual first failure was **GET /api/ai/investigations**, before any LLM call:
HTTP 500, PostgreSQL `UndefinedTable`, SQLSTATE `42P01`. The local database was
at revision `20250818_ops_settings` and had no `ai_investigations` table. The
frontend discarded the HTTP error detail and labelled it as backend unavailable
or timeout. This was not an LLM timeout, CORS problem, missing route, or wrong
`/api` prefix.

Applied the existing migrations using `cd backend` then
`python -m alembic upgrade head`. Current revision: `20260825_trigger_semantics`.
No new migration or table-creation shortcut was added.

A second, separate local configuration blocker is confirmed: `AI_PROVIDER` and
`AI_MODEL` are unset. A key is present (its value was never printed or changed).
The live POST now returns HTTP 503 with `AI_PROVIDER_NOT_CONFIGURED`, and the UI
displays that specific error. No model was chosen or paid call made implicitly.

## Restored UI and field bindings

Reused the original presentation primitives from the existing demo pages in
`InvestigationLayout.tsx`. Demo behaviour remains isolated behind API mode.

| Section | Structure retained | Live source |
| --- | --- | --- |
| Alert list | 28% width, 260–360px; compact rows, severity chips, zone filter | Operational alert DTOs, equipment and zones |
| Selected details | Central scroll area, 16px title, original section cards | Selected backend alert |
| Résumé | Description and Où / Depuis / Équipement / Confiance facts | Alert + equipment/zone DTOs; confidence from conclusion only |
| Pourquoi | Original section plus explicit hypotheses and uncertainty | `conclusion.summary`, `hypotheses`, `contradictions`, missing requests |
| Preuves / signaux | Evidence details and existing recent-film strip | Investigation evidence and provenance; operational timeline segments |
| Impact | Original card | Explicitly non-quantified; no numerical invention |
| Liens utiles | Carte / Film / Équipement buttons | Stable alert/equipment/zone/investigation context |
| Panel IA | 28% width, 240–340px; cause, confidence, impact, action cards | `conclusion.root_cause` or summary, qualitative confidence, recommendation description |
| Actions IA | Context header, 7/12 recommendation column, 5/12 simulation/reminder column | Persisted investigation UUID; retrieved with GET if not cached |
| Simulation / comparaison | Original visible area and disabled Simuler button | “Simulation d’impact non disponible en V1” |
| Human review | Préparer / Marquer / Ignorer | Explicit local review notes in existing workspace session state; no operational mutation |

Creating an investigation still requires an explicit click. Mount/rerender only
reads history. Shared in-flight deduplication and the pre-POST history lookup
remain. Ambiguous POST failures block automatic retries and permit read-only
recovery. Actions returns to the originating alert tab if it still exists.

## Errors, logs, timeouts

- API codes distinguish missing schema, database unavailable, provider not
  configured, persistence failure and investigation failure. Validation remains
  HTTP 422; invalid site/shift/equipment/zone scope is rejected.
- A storage preflight runs before provider invocation. Invalid shift/site
  combinations are rejected before creating an unpersistable record.
- Frontend transport distinguishes network failures, request timeout, HTTP
  rejection and safe backend codes. Arbitrary exception messages are never shown.
- Graph errors persist stage/type and a safe message. Server logs contain
  investigation ID, stage, exception type and stack locations. Provider logs
  contain model/schema/type/status/request ID, not request bodies or keys.
- Existing results remain visible if a later refresh fails.
- Synchronous V1 remains; no workers or scheduler were introduced. Provider
  timeout defaults to 45 seconds per request, no SDK retries, with a cumulative
  150-second LLM budget. Frontend POST timeout is 180 seconds, allowing overhead.
  These are SDK transport/cumulative call limits, not a hard wall-clock deadline
  for database queries; a transport timeout does not prove execution stopped.
- `.env.example` documents the settings and migration/preflight commands.
  Timeout/retry options were checked against the
  [official OpenAI Python SDK documentation](https://developers.openai.com/api/reference/python).

## Repeatable smoke commands

Run from `backend/`:

```sh
python scripts/smoke_ai.py --check-only
python scripts/smoke_ai.py --mock-provider --summary
python scripts/smoke_ai.py --mock-provider --in-process-api --summary
python scripts/smoke_ai.py --http-url http://127.0.0.1:8000 --summary
```

Without `--mock-provider`, execution requires the configured model and may incur
provider usage. Configure `AI_PROVIDER=openai` and an accessible structured-output
model in `AI_MODEL`, then restart the API. The script resolves current site/shift
via operational services and optionally uses an existing alert’s entity context.
It has no simulator import, scenario name, or hardcoded equipment/site ID.

All smoke records use unique `smoke-*` source identifiers, never a live alert’s
association ID. Mock outputs are labelled `smoke-test / no-llm` and explicitly say
they cannot be used for operational decisions. They are not runtime providers or
UI fallbacks. Two isolated test audit records were retained in the local DB:
`5767b071-bd32-4355-b3c3-749a24b2a1d9` and
`f13f86bc-c845-48c2-96b5-5e61d7e41c0f`.

## Verification

- Direct PostgreSQL → operational services → LangGraph → persistence/retrieval
  passed with the isolated test provider. Six evidence items, zero tool errors;
  status `COMPLETED_WITH_UNCERTAINTY`.
- Actual FastAPI handlers in-process: POST, GET by UUID and GET association all
  HTTP 200; retrieved result equals the persisted structured result.
- Live HTTP POST correctly reports `AI_PROVIDER_NOT_CONFIGURED` (503). The
  browser’s Investiguer click reaches the same route and shows the same safe
  error with no fabricated cause, confidence or recommendation.
- Browser DOM inspection confirms the original three-column sections, links,
  qualitative/unassessed states and real operational alert context. Successful
  result rendering and Actions binding are covered with mocked backend results,
  not claimed as a successful live LLM browser run.
- TypeScript checks and frontend production build pass. Vite retains its large
  chunk warning. Frontend suite: 66 passed. Backend suite: 76 passed, 2 skipped;
  existing Starlette/httpx deprecation warning. Python compilation and migration
  compilation pass. Alembic reports the applied head.
- Lint: exit 0, eight pre-existing warnings in demo/shared code.
- Repository search found no `simulator` references in the AI package or live
  investigation components/client/store. Boundary regression covers the smoke
  script as well.

**End-to-end status:** graph/API/storage and frontend bindings are verified with
mock reasoning. A successful real-provider → frontend investigation remains
unconfirmed until provider/model configuration is supplied. No optimization,
simulation engine, monitoring, frontend AI heuristics, MapLibre changes, global
UI redesign or operational-service rewrite was performed.

## Exact files changed in this corrective pass

The worktree already contained the earlier integration changes; this list covers
only files edited or created during this pass, not every file in `git status`.

Created:

- `backend/scripts/smoke_ai.py`
- `src/components/ai/InvestigationLayout.tsx`
- `docs/AI_UI_CORRECTIVE_PASS.md`

Modified (some were already untracked from the preceding integration):

- `.env.example`
- `backend/app/config.py`
- `backend/app/ai/llm/provider.py`
- `backend/app/ai/nodes.py`
- `backend/app/ai/persistence.py`
- `backend/app/ai/service.py`
- `backend/app/api/routes/ai.py`
- `backend/tests/test_ai_api.py`
- `backend/tests/test_ai_context_reconstruction.py`
- `backend/tests/test_ai_graph.py`
- `backend/tests/test_ai_provider.py`
- `backend/tests/test_ai_simulator_boundary.py`
- `src/pages/AlertesIA.tsx`
- `src/pages/ActionsIA.tsx`
- `src/components/ai/InvestigationAlerts.tsx`
- `src/components/ai/InvestigationActions.tsx`
- `src/components/ai/InvestigationResultView.tsx`
- `src/components/ai/integration.api.test.ts`
- `src/lib/ai/investigationPresentation.ts`
- `src/lib/api/client.ts`
- `src/lib/api/ai.ts`
- `src/lib/api/ai.test.ts`
- `src/lib/store/useInvestigationStore.ts`
- `src/lib/store/useInvestigationStore.test.ts`
