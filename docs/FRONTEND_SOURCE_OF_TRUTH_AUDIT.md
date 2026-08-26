# Frontend source-of-truth audit and LangGraph integration

Audit date: 2026-08-26. Scope: the existing MinePulse repository, not a new application.
This report covers every page and the data-bearing components/helpers beneath them. The exact file inventory is appended below.

## Outcome and scope

API mode now uses operational API results and persisted LangGraph investigations. Missing coverage is displayed as unavailable/non-evaluated, not replaced by demo values. Existing page purposes, workspace navigation and general panel layouts are retained; the live AI panels now represent the actual investigation lifecycle.

This is not a claim that every backend value is validated real-FMS data: PostgreSQL can still contain development data, and the OEM backend still has a test threshold/code catalog. Those limitations are explicitly identified below.

No LangGraph rewrite, new model/provider, database redesign, new migration, package/dependency update, simulator-engine rewrite, frontend monitoring scheduler, ML, optimization or autonomous control was implemented.

## AI integration and contracts

The existing endpoints remain authoritative:

| Endpoint | Purpose | Change |
| --- | --- | --- |
| POST /api/ai/investigations | Synchronously invoke the existing graph and return its persisted structured result | Existing endpoint reused |
| GET /api/ai/investigations/{investigation_id} | Retrieve one durable result by UUID | Existing endpoint reused |
| GET /api/ai/investigations?site_id=...&source_record_id=...&shift_id=... | Find the latest durable investigation for this operational source and scope (zero or one result) | Added read-only lookup, not a monitoring/list-all endpoint |

The lookup reuses AiInvestigation and its existing trigger_data JSON field; no new table or migration is required. The query is bounded to one record and scoped to site, source record and optional shift. A JSON source-record index/server-side idempotency is not added.

The centralized frontend boundary is src/lib/api/ai.ts. It delegates HTTP handling to the existing fetchJson client; no UI component performs raw fetch calls. src/lib/api/types/ai.ts is generated from the actual Pydantic InvestigationTrigger/InvestigationResult JSON schemas by backend/scripts/export_ai_types.py, with a drift-check test. No third-party codegen dependency was added.

The generated contract retains operational trigger type separately from trigger source, evidence kinds/statuses/provenance, request history, hypotheses, contradictions, conclusion, recommendation, qualitative confidence, nullability, timestamps, UUID, status and provider/model/graph metadata. Request fields with backend defaults remain optional; serialized response fields remain required.

The frontend does not guess the backend trigger taxonomy from alert prose. Explicit user investigation sends OPERATIONAL_EVENT + USER_INVESTIGATE, source alertes-ui, the alert ID as source_record_id and the original category/title/description payload. Site/shift/equipment/zone database IDs are provided as additive DTO fields; existing display-code IDs remain unchanged.

### Lifecycle and duplicate protection

1. Selecting/opening an alert performs a read-only lookup, never an LLM POST.
2. The operator clicks Investiguer. The shared Zustand investigation store rechecks durable history before starting.
3. Concurrent starts/lookups for the same site/shift/alert share one in-flight promise across renders and workspace mounts.
4. The synchronous POST displays Analyse IA en cours. The returned backend status distinguishes completed, completed-with-uncertainty and failed results. PENDING is represented if returned; there is no new queue.
5. Actions IA receives the investigation UUID and alert/equipment/zone IDs in workspace context, not a copied recommendation object. It retrieves the durable result when needed.
6. An ambiguous POST timeout/network failure blocks automatic re-POST. Read-only refresh can recover the persisted result. A transport error never manufactures an analysis.

No automatic retries, render-triggered investigations, browser background monitoring, or numeric confidence conversion are used. LOW/MEDIUM/HIGH become Faible/Moyenne/Élevée. Impact is always non quantifié for current graph output. Recommendations are advisory and require human validation.

Known limitation: deduplication is browser-store scoped, with a durable lookup before creation, not a transactional server uniqueness guarantee across multiple browsers/users or a full page reload during an in-flight POST. The existing backend only persists at the end of its synchronous run. A future queued/idempotent API is required for strict cross-client exactly-once behavior. No retry button for rerunning a completed/failed persisted investigation was added.

### Example

A persisted alert is selected on Alertes IA. GET lookup finds no result. The operator clicks Investiguer; POST carries the real alert ID, numeric site/shift IDs and original alert payload. Existing LangGraph resolves operational context, gathers approved operational/OEM evidence, diagnoses with its one configured provider, performs its bounded evidence expansion, builds a conclusion/recommendation and persists. Alertes IA displays the returned evidence IDs, qualitative confidence and unresolved uncertainty. Ouvrir Actions IA carries the UUID; Actions IA displays that same persisted recommendation. If the graph returns COMPLETED_WITH_UNCERTAINTY, both surfaces retain uncertainty; neither creates a gain estimate or dispatch action.

## Audit classification

A = presentational constants (keep); B = domain/configuration (review ownership); C = mock/demo (only false mode); D = live operational (backend); E = AI (LangGraph backend).

FIXED means the identified leak/misrepresentation was corrected, not that missing backend functionality was implemented.
OK means verified already backend-backed or safely presentational. PARTIAL/BLOCKED identify actual missing coverage.

## Page and component evidence table

| Page/component | Field/data | Previous source | Correct source | Status | Action |
| --- | --- | --- | --- | --- | --- |
| Alertes IA | Operational alerts, severity, location, time | Operational store/bootstrap | list_site_alerts and alert DTOs | OK (D) | Retained backend values; filters only select/display rows |
| Alertes IA | Cause, rationale, signals, confidence | alertIntelligence -> investigateException frontend heuristics | Persisted InvestigationResult | FIXED (E) | Dedicated API surface; no mock intelligence call in API mode |
| Alertes IA | Missing analysis | Synthetic confidence / old pseudo-analysis | Explicit absent/loading/running/error/result states | FIXED (E) | No confidence 0%; qualitative confidence only after analysis |
| Alertes IA | Prediction tab/scenario forecasts | predictions.ts scenario constants | No V1 prediction backend | BLOCKED (E) | API surface says predictions unavailable; demo tab retained |
| Alertes IA | Evidence and uncertainty | Frontend narrative | Backend evidence, hypothesis links, contradictions, missing requests | FIXED (E) | IDs, service/timestamp provenance and null values rendered |
| Alertes IA -> Actions IA | Recommendation context | Frontend generated issue/recommendation payload | investigation_id plus source IDs | FIXED (E) | Durable retrieval and workspace context persistence |
| Actions IA | Recommendation | dispatchOptimizationBundle, seeded dispatch logic | Backend investigation.recommendation | FIXED (E) | No fake assignments or dispatch actions in API mode |
| Actions IA | Gains, wait/cycle improvement, before/after numbers | Scenario dispatch/projectSnapshot arithmetic | No optimization/simulation backend result | BLOCKED (E) | Non-evaluated / impact non quantifié; no execution controls |
| Performance production | Actual, target, gap, attainment | Existing backend production rollup | production_summary / shiftly_attainment | OK (D) | No redefinition of attainment; null target stays null |
| Performance production | Hourly active truck counts | Current fleet count repeated into historical buckets | No historical active-count field | FIXED (D) | Null instead of pseudo-history |
| Performance production | Severity tint, explanation, confidence | Local attainment threshold / narrative / numeric confidence | Backend values; no analysis performed here | FIXED (B/E) | Neutral API presentation and Non évalué |
| Performance fuel | Per-engine l/h | Backend telemetry DTO | latest_telemetry / fleet DTO | OK (D) | Render raw measured rate or unavailable |
| Performance fuel | Shift litres, idle litres, L/t, fleet average | Engine-hours modulo/assumed hours, capacity/load multipliers, mean of rates | Not exposed as authoritative aggregates | FIXED / BLOCKED (D) | Removed API calculation path; null metrics and missing-information copy |
| Performance cycle | Per-engine average and completed cycles | Backend DTO | avg_cycle_minutes_bulk / shift_trip_counts | OK (D) | Keep server values |
| Performance cycle | Fleet average, summed sample totals, stage averages | Frontend mean-of-means / sample-limited totals / missing stage zero | Not exposed at fleet level | FIXED / BLOCKED (D) | No API aggregate reconstruction; target uses server shift targetCycleMin |
| Performance waiting | Current located trucks per zone | Inventory grouping | Current backend equipment zone IDs | OK (D presentation) | Explicitly labeled current inventory, not average queue |
| Performance waiting | Average/max queue, lost time, historical zone wait | Current position + cumulative waiting heuristics | Missing historical queue service response | FIXED / BLOCKED (D) | Null; graph shows backend per-equipment cumulative shift wait |
| Performance TD/TU | Per-equipment percentages | Backend operational service | td_tu_pct_bulk | OK (D) | No frontend percentage formula |
| Performance TD/TU | Fleet percentages | Average of individual percentages | No weighted fleet aggregate exposed | FIXED / BLOCKED (D) | Unavailable instead of second definition |
| Performance voyages | Per-equipment trips/cycle/wait | Backend DTO | cycles/equipment services | OK (D) | Retain source values |
| Performance voyages | Per-machine tonnage | Trips * instantaneous payload/capacity assumption | Missing per-machine tonnage response | FIXED / BLOCKED (D) | Null; no payload-to-production inference |
| Performance downtime | Category/hours | Backend downtimeReasons | downtime_reasons | OK (D) | Direct category/hours rendering |
| Performance downtime | Root cause, event status, no-cause classification | Text matching and synthetic interpretation | Missing validated cause/event association | FIXED / BLOCKED (D/E) | No invented classification; hide unsupported API no-cause filter |
| Performance charts/tables | Empty or all-null series | Potential empty-looking graph | Explicit absence of numeric data | FIXED (D) | Unavailable message; null cells remain dashes |
| Performance dates | Multi-day selectors vs shift-only fetched aggregates | Local selected dates, unchanged backend period | Dated server-selected shift | FIXED (D) | API period clearly shift-only; demo date behavior retained |
| Performance documents | Example PDF/document list | Static demonstration documents | No document API | FIXED / BLOCKED (C/D) | Only demo shows example entries |
| Performance XLSX | Confidence/source values | Numeric pseudo-confidence metadata | Same null-safe API analysis | FIXED (E) | Non évalué in export; no new metrics during export |
| Carte | Equipment coordinates, speed, heading, payload, state | Existing API DTOs | Positions/telemetry/equipment services | OK (D) | Null position omitted, speed/heading not zero-filled |
| Carte popup | Duration in current state | now - last telemetry update | No stateSince field exposed | FIXED / BLOCKED (D) | Unavailable in API mode |
| Carte | Recent path / moving markers | Frontend simulated trail/heading extrapolation | No persisted GPS-history endpoint | FIXED / BLOCKED (C/D) | API simulation hooks no-op; path overlay disabled |
| Carte | Congestion, occupancy severity, average waiting | Local count > capacity and current-zone wait inference | No authoritative congestion/zone-wait field | FIXED / BLOCKED (D) | No congestion inference; neutral count display; wait unknown |
| Carte roads | Restricted/main classification | Endpoint-zone type heuristic | No authoritative road-status field | FIXED (D) | Neutral cartographic style; does not assert open/closed |
| Carte | Site bounds and coordinate transform | SITE_GEO constants | Existing backend/frontend workspace projection convention | REVIEWED (B) | Retained matching transform; multi-site geometry config remains a backend gap |
| Carte | Empty fleet fit bounds | Infinity bounds from missing positions | No available position | FIXED (D presentation) | Return null; no invented coordinate |
| Carte zone editor | Capacity unknown | Default/forced minimum | Backend nullable capacity / explicit user input | FIXED (D/B) | Preserve null and real zero; edits remain intentional user CRUD |
| Carte navigation | Selected alert/equipment/zone | Partial workspace handling | Existing workspace IDs | FIXED (D presentation) | Accept workspace context and focus actual entities |
| Film | Timeline segments/state/zone | Backend timelineSegments | timeline_for_shift | OK (D) | No synthetic state history in API branch |
| Film | Dated shift / elapsed period | Client reconstruction/current date | shift_window serialized in bootstrap | FIXED (D) | Missing time/window is unavailable, historical window not replaced by today |
| Film | Segment AI interpretation | Placeholder helper | No investigation result attached | OK with guard (E) | AiSlot shows non-evaluated in API mode, never demo confidence |
| Parc/fleet interface | Equipment table/cards | Operational store | Backend fleet DTO | OK (D) | No standalone Parc page exists; fleet surfaces are Carte/Film/equipment detail |
| Equipment page/drawer | State, assignment, operator, trips, TD/TU, health | Backend enriched DTO | Equipment/assignment/cycle services + DTO | OK (D) | Render provided values, no health default |
| Equipment detail | Destination/task text | Generic loaded/empty load/dump assumptions | Backend assignment when present | FIXED (D) | Unknown destination/task is explicitly unrecorded |
| Equipment detail / Carte | Missing operator | Non affecté inferred from absent lookup | Recorded operator or unknown | FIXED (D) | Opérateur non renseigné in API mode; no invented assignment absence |
| Equipment detail | Waiting/idle presentation | Local ratio/complement of shift window | Backend waitingMinutesThisShift / idleMinutesThisShift | FIXED (D) | Raw backend durations; no fake active-time remainder |
| Equipment detail | Latest telemetry timestamp | now fallback | Actual telemetry timestamp | FIXED (D) | Missing timestamp stays unavailable |
| Equipment detail | Fuel warning | Local fuel thresholds | No matching authoritative condition | FIXED (B) | Neutral API display, demo colors preserved |
| Equipment maintenance | Next-service/250 h estimate | Frontend modulo formula | No forecast service | FIXED / BLOCKED (D) | Non évalué; actual history retained |
| Equipment maintenance history | Duration and technician | Expected end / minimum duration / generic Maintenance name | Actual end and recorded technician metadata | FIXED (D) | Backend mapper now returns null when unknown |
| Equipment maintenance history | Loading/error/empty | Ambiguous empty history | Distinct request states | FIXED (D) | Operator sees loading, failed load, or truly empty history |
| CycleStepper/CycleBreakdown | Incomplete total and per-stage target/outlier | null=0, avg/6, 10% frontend heuristic | Actual stages and backend stage flags | FIXED (D/B) | Incomplete total unknown; complete-stage sum is display composition, not fleet KPI |
| MiniTimelineStrip | Time gaps | Flex-proportional contiguous segments | Actual start/end offsets | FIXED (D presentation) | Gaps remain visible; segments are not moved together |
| OEM all seven workspaces | Site/shift scope | Many calls silently used backend default scope | Central scopedOemApi using selected context | FIXED (D) | All telemetry/diagnostic/maintenance/connectivity requests scoped |
| OEM all workspaces | Failed refresh/stale export | Old successful rows could remain | Current request/context only | FIXED (D) | Errors clear data; keyed context/filter views and scoped export payloads |
| OEM period controls | Date/shift query | Local shift reconstruction / ignored date control | Server dated shift windows or explicit valid custom ISO window | FIXED (D) | Missing window is rejected; no invented current date for data |
| OEM connectivity | State/quality/last telemetry/delays | Backend connectivity service | fleet_connectivity / communication_delays | OK (D) | Source-owned status; no frontend online/offline business formula |
| OEM connectivity | Unknown connected/disconnected durations | null -> 0; fabricated one-hour empty track | ping_diagram / ping_fleet, or explicit unknown | FIXED (D) | No fake empty timeline; null durations dashes, measured zero visible |
| OEM connectivity | Delay filter and red cells | Filter control not applied; generic >30 threshold on durations | Explicit user filter / backend status | FIXED (B/D) | Filter known returned delays; remove generic duration alarm coloring |
| OEM diagnostic | Parameter min/avg/max | Backend telemetry queries | diagnostic_parameters | OK (D) | No frontend generated telemetry |
| OEM diagnostic | Sensor working / classification | Latest missing could imply working; hidden test thresholds | Source classification/provenance or null | FIXED / PARTIAL (B/D) | Unknown latest value not Oui/OK; display thresholdSource |
| OEM diagnostic error codes | SIM catalog descriptions/severity | Backend test catalog without UI provenance | Persisted events + explicit catalogSource | PARTIAL (B/D) | Label simulation/test; real manufacturer code catalog not implemented |
| OEM maintenance | Indicator values, red/yellow counts | Backend maintenance_indicators | Same backend measurements/definitions | OK (D), PARTIAL (B) | Surface test thresholdSource; no manufacturer claim |
| OEM maintenance anomalies | Ranges/severity/duration | Event payload or backend test catalog | Same provenance-labelled sources | PARTIAL (B/D) | Expose source event vs test threshold/catalog; missing duration stays unknown |
| OEM pneus | Pressure/temperature series | Persisted tyre telemetry; backend null -> 0 | get_tyre_history | FIXED (D) | Null pressure/temp stays null; true zero remains zero |
| OEM pneus | Tyre positions | Frontend hard-coded list | /oem/catalog tyrePositions | FIXED (B) | Backend catalog drives choices |
| OEM vitesse/gasoil | Time series | Backend telemetry history | get_equipment_signal_history | OK (D) | Null data/gaps preserved; scoped requests |
| OEM poids | Payload/speed/fuel | Backend telemetry history | get_equipment_signal_history | OK (D) | No synthesized payload or consumption |
| OEM multi-signaux | Signal catalog/series | Backend catalog/telemetry | Same services | OK (B/D) | Labels/units/default selection only; no generated series |
| OEM trees/tabs/filter selectors | Equipment and signal options | Operational store / OEM catalog; static navigation labels | Same | OK (A/B) | Type filtering/grouping is presentation |
| OEM chart/table/export components | Values and units | Caller/API data | Same values, null-safe rendering | OK / FIXED (D presentation) | Real zero alarm counts shown; no Simulation:true export claim |
| Paramètres | Operational thresholds | Default store values before API loaded | get_operational_settings / PATCH response | FIXED (B) | settingsLoaded gate; failure not disguised as defaults |
| Paramètres | Site region/pits | Mapper injected Simulation / Panneau 1 | Recorded region; no pits endpoint | FIXED / BLOCKED (D) | Null region, empty pits; unavailable UI |
| Paramètres | Shift target/scenario summary | MERAH_SHIFT_SCENARIO | Backend rollup in API mode | OK guarded (C/D) | Scenario summary remains demo-only |
| Paramètres | Unit toggle | Imperial selection without implemented conversions | Supported display contract | FIXED (B) | Disable unsupported live imperial selection |
| Paramètres | Simulation link | DEV label but available in production routing | Explicit dev-only tool | FIXED (C) | import.meta.env.DEV route/link gate; excluded from production bundle |
| Global header | User/role/session | Static CP/Chef de poste/Session active | No auth/profile backend | FIXED / BLOCKED (D) | Session locale / auth unconfigured; no fake authenticated identity |
| Global header alerts menu | Alert rows/count | Operational store | Backend alerts | OK (D) | API error distinguished from no alerts |
| Global shift/site strip | Context, production/attainment | Backend rollup mixed with local time projection | Backend context/window/production | FIXED (D) | No midnight wrap or local attainment severity threshold |
| DataFreshnessIndicator | LIVE label | Successful API poll implied live sensors | API transport sync only | FIXED (D) | API SYNCHRONISÉE, explicit sensor-freshness disclaimer |
| Command palette | Equipment/operator matches | Operational store | Same | OK (D presentation) | No hardcoded operational entities |
| Workspace tabs/navigation | Titles, dedup keys, selected IDs | Workspace store/sessionStorage | Same IDs, now including investigation UUID | OK (A/D presentation) | Preserve selected context, not AI payload copies |
| Shared KPI/legends/badges | Labels, colors, units, styles | Static presentation props/constants | Same | OK (A) | No removal of legitimate labels/design tokens |
| Shared OperationalBrief | Scenario briefing | MERAH scenario | No live implementation | OK guarded (C) | Returns null in API mode |
| Shared ScenarioComparison | Before/after demo figures | Demo ActionsIA caller | No live optimization | OK guarded caller (C) | Retained only for demo path |
| Shared AiSlot | Placeholder intelligence | Hash-seeded confidence/advice | No attached AI result | FIXED (E) | API guard ignores passed demo insight entirely |
| AppShell/polling/store | Initial world, scope changes, sync errors | API-empty initial state; possible stale previous scope | Fresh selected-scope API response | FIXED (D) | Clear scoped arrays/context on switch; reject stale asynchronous poll results |
| SimulationCentre (DEV only) | Test-world controls/data | Explicit simulation API | Explicit simulation API, not operational source | KEPT (C/dev) | No production route; null speed/fuel/payload/queue now unavailable even here |
| SimulationCentre (DEV only) | Injection values, speeds, durations, example search hint | Deliberate test/control inputs | Same | KEPT (C/A) | Inputs are not measured operational facts |

## Frontend business calculations found and resolved

The live path no longer computes shift fuel from modulo engine hours, estimates production from capacity/payload, averages individual availability/cycle ratios into fleet KPIs, localizes historical waiting using current zone, infers queues/congestion from current occupancy, infers root causes from stop text, or fabricates AI confidence/dispatch gains. Those concepts either use the existing backend field or remain unavailable.

Remaining frontend arithmetic is presentation: rounding/units, ordering/filtering, counts of displayed/current rows (clearly labeled), coordinate projection, dated-window positioning, complete stage-value display sums, and UI progress/layout. Per-shift production attainment continues to use the already-authoritative backend rollup. Demo business arithmetic remains confined to the false-mode branch.

Old nonproduction builders in metrics.ts remain private demo paths behind the early API return to apiMetrics.ts; any legacy API ternaries inside them are unreachable. They were not mechanically rewritten to avoid perturbing the intentional demo calculations. Their numeric zero-confidence alternatives have nevertheless been changed to null.

## Static content retained deliberately

- A: navigation/tab titles, French translations, icons, equipment/status color palettes, chart styles, table columns, help copy, date/export formatting and display units. A label/unit is not a measurement.
- B: UI enum/label translations mirror API vocabulary. OEM sensors/positions/threshold provenance come from the backend catalog. Settings thresholds come from the backend, not initial store defaults. The 30-second API sync badge cutoff is a transport-UI setting, not equipment connectivity classification. User-entered filters and zone-edit defaults are inputs, not facts.
- B limitation: SITE_GEO is the existing shared-by-convention single-site workspace projection; no new fake coordinates are supplied. Per-site map projection metadata should become backend configuration before adding arbitrary sites.
- C: mock/generator.ts, scenario.ts, performanceFacts.ts, scenarioMetrics.ts, demo page bodies, mock dispatch/predictions and map animation remain useful demonstrations. Types and label constants currently live in lib/mock/types.ts but are shared DTO definitions, not runtime demo entities.
- Randomness remains only in the guarded demo tick/scenario generators and workspace UI ID generation. Random workspace IDs are not operational values.
- D: operational snapshots, assignments, alerts, timeline, production and OEM series come through normal operational API paths. The frontend does not consume SimWorld or simulator files.
- E: live hypotheses/conclusion/confidence/recommendation/evidence come only from the persisted LangGraph result. Future MODEL_PREDICTION remains its distinct generated evidence kind; no ML output is relabeled FACT.

## Legacy helpers and dead-code disposition

Kept for demo use: alertIntelligence.ts, predictions.ts, exceptionInvestigation.ts, dispatch.ts, placeholders.ts, ScenarioComparison and OperationalBrief. The API page wrappers never invoke demo page bodies. Defense-in-depth guards return no mock intelligence or a non-evaluated view in API mode; investigateException explicitly refuses live use.

Removed the unused legacy EventInspector, ExceptionInspector, BeforeAfterSim, ConstraintsRail, DispatchActionList and ImpactSummary components after reference inspection. They had no current consumers. Removed the unused fetchSimulationStatus export from the general operational client; explicit DEV controls keep their own simulation client. These removals are recoverable from Git.

No mock files, simulator engine files, active demo pages, operational SQL definitions, or provider implementations were deleted.

## Simulator/FMS boundary

Production route: real FMS OR temporary simulator -> PostgreSQL/ingestion -> operational/OEM services -> FastAPI -> frontend.
AI route: the same operational services -> existing approved AI adapters -> LangGraph -> durable result -> frontend.

The frontend's live AI components, AI client and live Performance presenter have no scenario imports. Production components do not import simulator internals or the simulation API. SimulationCentre is the intentional exception and is now dev-build only. Legacy names simNow/useLiveSimulation refer to the backend operational timestamp and API polling branch; no simulator clock is instantiated in the browser. Optional bootstrap simulation metadata is not required to render live surfaces.

Existing AI simulator-boundary tests and a repository import search confirm no direct simulator imports under backend/app/ai/. No change to graph orchestration was required.

Important remaining backend qualification: OEM threshold and event-code catalogs still include SIM_* definitions inside app/oem, and existing application startup can still initialize simulation infrastructure. These are existing backend concerns, not dependencies introduced into the live AI/frontend layer. Replacing data sources must preserve operational contracts; manufacturer-validated OEM classification requires a real catalog rather than relabeling the existing test one.

## API MODE SOURCE-OF-TRUTH STATUS

| Main interface | Classification | Remaining gap |
| --- | --- | --- |
| Alertes IA | MOCK LEAK FOUND/FIXED | Configured provider and existing AI tables required; V1 predictions absent |
| Actions IA | MOCK LEAK FOUND/FIXED | Advisory recommendation only; optimization/impact BLOCKED BY MISSING BACKEND DATA |
| Performance | PARTIALLY BACKED | Weighted fleet aggregates, integrated fuel, historical queues, validated causes and documents |
| Carte | PARTIALLY BACKED | GPS history, congestion/zone waiting, state duration, general multi-site projection |
| Film | CLEAN for returned timeline | Detailed cause/investigation attachment not provided; missing windows explicit |
| Parc/fleet lists (embedded; no standalone page) | PARTIALLY BACKED | Backend coverage/health provenance limits; no fabricated supplement |
| Equipment detail/drawer | PARTIALLY BACKED | Maintenance prediction and GPS history unavailable |
| OEM connectivité | CLEAN for exposed service contract | Backend interval/coverage semantics still apply |
| OEM diagnostic | PARTIALLY BACKED | Test catalog, not validated manufacturer thresholds/codes |
| OEM maintenance | PARTIALLY BACKED | Test threshold classification; no maintenance prediction |
| OEM pneus | MOCK LEAK FOUND/FIXED | Requires actual tyre telemetry coverage |
| OEM vitesse/gasoil | CLEAN | Missing samples remain missing |
| OEM poids | CLEAN | Missing samples remain missing |
| OEM multi-signaux | CLEAN | Only catalog-supported telemetry exposed |
| Paramètres | PARTIALLY BACKED | No pit/site-catalog/auth/document backend; metric-only display |
| Header / site-shift strip / alerts menu | MOCK LEAK FOUND/FIXED | User authentication intentionally unconfigured |
| Navigation / shared presentational components | CLEAN | IDs and labels only; non-evaluated generic AI slots |
| SimulationCentre | DEV ONLY, excluded from production | Deliberate temporary test tool, not live operational truth |

CLEAN means no identified frontend fabrication in the reviewed API path; it does not certify upstream sensor freshness, ingestion completeness or domain accuracy of backend formulas.

## Backend and compatibility concerns

1. Deploy frontend and backend together: new numeric databaseId and dated shift-window fields are additive, but the live investigation button requires the numeric site identity. An older backend yields an explicit unavailable identity rather than parsing display codes.
2. Existing AI migrations must already be applied (current head: 20260825_trigger_semantics). No migration was added/applied in this pass.
3. Existing settings remain: VITE_USE_API=true, VITE_API_BASE as appropriate; backend AI_PROVIDER=openai, AI_MODEL, OPENAI_API_KEY, AI_MAX_INVESTIGATION_ITERATIONS (default 3). .env.example already documents these. Never put provider secrets in VITE_* variables.
4. Only the existing OpenAI provider implementation is supported here. A missing provider is an explicit 503; runtime graph failure is displayed from its durable FAILED result. No paid API was called during tests.
5. Backend operational no-row semantics still warrant a separate ingestion-quality review: some completed-trip/wait counters default to zero; TD/TU state coverage can imply 100/0 with no state rows. The frontend does not reinterpret those returned numbers. Coverage flags are needed upstream to distinguish true measured zero from absence.
6. Backend OEM range parsing caps large ranges, and some latest-value/current connectivity fields use latest snapshots while interval statistics use the selected range. The frontend no longer invents these fields, but complete historical/as-of semantics belong in backend contracts.
7. The current backend bootstrap exposes one selected site rather than an all-sites/pits catalog. No frontend fake site/pit rows were added.
8. Operational TypeScript DTOs remain manually maintained in the existing lib/mock/types.ts location; the older lib/api/types/ops.ts duplicate is not a live source and was not broadly refactored. AI types are schema-generated and checked.
9. General HTTP errors now expose status codes rather than arbitrary response bodies/stack traces. This is safer but less detailed than some previous validation error strings.
10. No cross-client idempotency key, long-running job status API, checkpoint recovery, auth/authorization/rate-limiting changes or browser-persisted in-flight run token was implemented. These remain production deployment considerations for an expensive synchronous POST.

## Validation and regression coverage

Executed using the existing installed Node/Python dependencies; no new packages:

| Check | Result |
| --- | --- |
| node node_modules/typescript/bin/tsc -b --pretty false | PASS |
| node node_modules/vitest/vitest.mjs run | PASS: 55 tests in 16 files |
| node node_modules/vite/bin/vite.js build | PASS: production build; simulation control chunk absent |
| node node_modules/oxlint/bin/oxlint | Exit 0; 8 existing warnings (Fast Refresh exports, demo ActionsIA hook deps, design-token script unused variable) |
| python -m pytest -q (backend) | PASS: 67 passed, 2 opt-in integration tests skipped; one existing Starlette/httpx deprecation warning |
| python -m compileall -q app tests scripts alembic (backend) | PASS, including migration syntax |
| python -m alembic heads (backend) | PASS: single existing head 20260825_trigger_semantics |
| python scripts/export_ai_types.py --check (backend) | PASS: generated TypeScript matches current Pydantic schema |
| rg direct simulator import search in backend/app/ai | No matches (expected exit 1) |
| git diff --check | PASS (Windows line-ending notices only) |

New frontend tests cover real backend AI rendering, mock-helper refusal in API mode, demo rendering, Actions UUID/result behavior, absent/running/uncertain/failed states, no render POST, concurrent-start deduplication, durable reuse, ambiguous-failure non-retry, null/zero distinction, map no-position/no-synthetic-trail behavior, cycle unknowns, OEM scope and unknown durations, server shift windows, stale context clearing, workspace navigation persistence, and simulator import boundaries.

New backend tests cover schema/typegen drift, scoped durable lookup, GET without graph execution, query validation, additive identity/no fake region/pits, unfinished maintenance nulls, tyre null vs zero, and unknown diagnostic sensor status with explicit threshold provenance. Existing backend AI trust/loop/provider/context/persistence/simulator tests also passed.

Validation limitations: frontend integration tests use server rendering and mocked stores/APIs plus store-level concurrency tests, not browser end-to-end interaction. No paid LLM, live PostgreSQL round-trip, real FMS, visual browser verification, or deployment migration execution was performed. The two backend integration tests require explicit --integration and were not run. Sandbox initially blocked Vite/Vitest worker execution; rerunning those local checks with approved escalation succeeded. Large xlsx/map build chunks still produce the existing size warning.

## Inventory and exact change manifest

The following inventory is generated from repository file paths, not a claim that UI primitives each have independent business logic. All pages and data-bearing modules were inspected; UI primitive groups were verified as prop-driven/presentational. Exact created/modified/deleted paths follow.

### Audited file ledger

| File | Classification / verification |
| --- | --- |
| src/App.tsx | A/C — navigation; simulation lazy import and route are DEV-only |
| src/components/ai/AiSlot.tsx | C/E — API-mode non-evaluated guard; demo insight only otherwise |
| src/components/ai/InvestigationActions.tsx | E — live persisted investigation result/transport state |
| src/components/ai/InvestigationAlerts.tsx | E — live persisted investigation result/transport state |
| src/components/ai/InvestigationResultView.tsx | E — live persisted investigation result/transport state |
| src/components/ai/integration.api.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/components/ai/integration.demo.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/components/brand/OcpLogo.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/dashboard/ProductionTrendChart.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/equipment/EquipmentDetailContent.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/equipment/EquipmentDetailDrawer.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/equipment/EquipmentTypeIcon.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/equipment/MiniTimelineStrip.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/layout/AppShell.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/layout/BrandHeader.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/layout/CommandPalette.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/layout/PosteBar.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/map/EquipmentLayer.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/EquipmentPopup.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/HaulRoadsLayer.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/MapControls.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/MapLegend.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/MineMap.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/MineMapContext.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/OperationalZonesLayer.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/RecentPathLayer.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/ZoneDraftLayer.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/ZoneEditor.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/ZoneEditorPanel.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/map/ZoneVertexLayer.tsx | B/D — backend geometry/DTO or user edit/presentation; no API synthetic history |
| src/components/oem/OemCatalogMenu.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemConnectivityTimeline.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemDataTable.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemEmptyState.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemEquipmentTree.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemExportButton.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemFilterPanel.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemInternalTabs.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemParameterSelector.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemReportLayout.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/OemSyncedCharts.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/oemViewUtils.ts | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/AnalyseCharts.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/AnomaliesTable.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/ConnectivityReport.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/DiagnosticWorkspace.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/ErrorCodesTable.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/IndicatorsTable.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/MaintenanceWorkspace.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/MultiSignalExplorer.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/ParametersTable.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/PayloadSpeedFuelCharts.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/SpeedFuelCharts.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/oem/views/TyreCharts.tsx | B/D — scoped OEM API/catalog or prop-only presentation; test provenance explicit |
| src/components/parc/CycleStepper.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/performance/ExportExcelButton.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/performance/PerformanceChart.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/performance/PerformanceTable.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/AppErrorBoundary.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/ContextHeader.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/CycleBreakdown.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/DataFreshnessIndicator.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/FilterDrawer.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/KpiCard.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/OperationalBrief.tsx | C — demo-only briefing/comparison path |
| src/components/shared/PeriodFilters.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/shared/ScenarioComparison.tsx | C — demo-only briefing/comparison path |
| src/components/shared/StatusLegend.tsx | A/D — backend-store/prop presentation; see page table for individual gaps |
| src/components/ui/badge.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/button.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/card.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/command.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/dialog.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/dropdown-menu.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/input.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/label.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/popover.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/progress.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/scroll-area.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/select.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/separator.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/sheet.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/switch.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/table.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/tabs.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/textarea.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/ui/tooltip.tsx | A — prop-driven UI primitive / brand asset, no operational source |
| src/components/workspace/ModuleRouteSync.tsx | A — navigation/context IDs, no generated measurements |
| src/components/workspace/WorkspaceHost.tsx | A — navigation/context IDs, no generated measurements |
| src/components/workspace/WorkspaceTabBar.tsx | A — navigation/context IDs, no generated measurements |
| src/components/workspace/useWorkspaceKeyboard.ts | A — navigation/context IDs, no generated measurements |
| src/features/map/map.constants.ts | A/B/D — geometry projection/styles and null-safe backend feature mapping |
| src/features/map/map.geo.ts | A/B/D — geometry projection/styles and null-safe backend feature mapping |
| src/features/map/map.icons.ts | A/B/D — geometry projection/styles and null-safe backend feature mapping |
| src/features/map/map.simulation.ts | C — API no-op guards around demo movement/trails |
| src/features/map/map.types.ts | A/B/D — geometry projection/styles and null-safe backend feature mapping |
| src/features/map/map.utils.ts | A/B/D — geometry projection/styles and null-safe backend feature mapping |
| src/lib/ai/alertIntelligence.ts | C — retained demo intelligence; excluded/guarded in live mode |
| src/lib/ai/dispatch.api.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/ai/dispatch.ts | C — retained demo intelligence; excluded/guarded in live mode |
| src/lib/ai/exceptionInvestigation.ts | C — retained demo intelligence; excluded/guarded in live mode |
| src/lib/ai/investigationPresentation.ts | A/E — enum translations and honest lifecycle labels |
| src/lib/ai/placeholders.ts | C — retained demo intelligence; excluded/guarded in live mode |
| src/lib/ai/predictions.ts | C — retained demo intelligence; excluded/guarded in live mode |
| src/lib/api/ai.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/api/ai.ts | D/E — centralized transport/contracts; AI schema generated |
| src/lib/api/client.ts | D/E — centralized transport/contracts; AI schema generated |
| src/lib/api/oem.scope.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/api/oem.ts | D/E — centralized transport/contracts; AI schema generated |
| src/lib/api/opsQuery.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/api/simulation.ts | C — explicit DEV control transport only |
| src/lib/api/types/ai.ts | D/E — centralized transport/contracts; AI schema generated |
| src/lib/api/types/ops.ts | D/E — centralized transport/contracts; AI schema generated |
| src/lib/equipment-icons.ts | A/B — labels, formatting, ordering, utility/icon definitions |
| src/lib/equipment/contribution.api.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/equipment/contribution.ts | D — backend rollup/window display; no API business redefinition |
| src/lib/equipmentOrder.ts | A/B — labels, formatting, ordering, utility/icon definitions |
| src/lib/export/oemXlsx.ts | A/D — exports existing presented values, no operational generation |
| src/lib/export/performanceXlsx.ts | A/D — exports existing presented values, no operational generation |
| src/lib/format.ts | A/B — labels, formatting, ordering, utility/icon definitions |
| src/lib/hooks/useLiveSimulation.ts | D/E — scoped API mode branch, demo branch guarded; navigation state is local |
| src/lib/mock/generator.ts | C — guarded scenario/demo data and metrics |
| src/lib/mock/performanceFacts.ts | C — guarded scenario/demo data and metrics |
| src/lib/mock/scenario.ts | C — guarded scenario/demo data and metrics |
| src/lib/mock/scenarioMetrics.api.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/mock/scenarioMetrics.ts | C — guarded scenario/demo data and metrics |
| src/lib/mock/types.ts | B/D — shared DTO types, labels; not a generated mock world |
| src/lib/oem/format.ts | A/B/D — catalog types, filter defaults, IDs and null-safe formatting |
| src/lib/oem/openOem.ts | A/B/D — catalog types, filter defaults, IDs and null-safe formatting |
| src/lib/oem/types.ts | A/B/D — catalog types, filter defaults, IDs and null-safe formatting |
| src/lib/ops/shiftWindow.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/ops/shiftWindow.ts | D — backend rollup/window display; no API business redefinition |
| src/lib/performance/apiMetrics.ts | D/C — API presentation branch separate from demo business arithmetic |
| src/lib/performance/metrics.api.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/performance/metrics.ts | D/C — API presentation branch separate from demo business arithmetic |
| src/lib/production/mergeProduction.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/production/mergeProduction.ts | D — backend rollup/window display; no API business redefinition |
| src/lib/sourceOfTruth.api.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/status.ts | A/B — labels, formatting, ordering, utility/icon definitions |
| src/lib/store/apiSync.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/store/apiSync.ts | D/E — scoped API mode branch, demo branch guarded; navigation state is local |
| src/lib/store/useInvestigationStore.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/store/useInvestigationStore.ts | D/E — scoped API mode branch, demo branch guarded; navigation state is local |
| src/lib/store/useOpsStore.alerts.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/store/useOpsStore.ts | D/E — scoped API mode branch, demo branch guarded; navigation state is local |
| src/lib/store/useUiStore.ts | D/E — scoped API mode branch, demo branch guarded; navigation state is local |
| src/lib/store/useWorkspaceStore.ts | D/E — scoped API mode branch, demo branch guarded; navigation state is local |
| src/lib/store/workspace.investigation.test.ts | Test-only; mocked transport/domain regressions, not runtime data |
| src/lib/utils.ts | A/B — labels, formatting, ordering, utility/icon definitions |
| src/lib/workspace/titles.ts | A — navigation/context IDs, no generated measurements |
| src/lib/workspace/types.ts | A — navigation/context IDs, no generated measurements |
| src/pages/ActionsIA.tsx | Reviewed page — see per-field findings above |
| src/pages/AlertesIA.tsx | Reviewed page — see per-field findings above |
| src/pages/EquipmentPage.tsx | Reviewed page — see per-field findings above |
| src/pages/Parametres.tsx | Reviewed page — see per-field findings above |
| src/pages/Performance.tsx | Reviewed page — see per-field findings above |
| src/pages/dev/SimulationCentre.tsx | C — explicit DEV-only simulation client, excluded from production |
| src/pages/oem/OemPage.tsx | Reviewed page — see per-field findings above |
| src/pages/supervision/Carte.tsx | Reviewed page — see per-field findings above |
| src/pages/supervision/Film.tsx | Reviewed page — see per-field findings above |
| src/pages/supervision/SupervisionLayout.tsx | Reviewed page — see per-field findings above |

### Created: 19 files

- backend/scripts/export_ai_types.py
- backend/tests/test_frontend_integration.py
- docs/FRONTEND_SOURCE_OF_TRUTH_AUDIT.md
- src/components/ai/InvestigationActions.tsx
- src/components/ai/InvestigationAlerts.tsx
- src/components/ai/InvestigationResultView.tsx
- src/components/ai/integration.api.test.ts
- src/components/ai/integration.demo.test.ts
- src/lib/ai/investigationPresentation.ts
- src/lib/api/ai.test.ts
- src/lib/api/ai.ts
- src/lib/api/oem.scope.test.ts
- src/lib/api/types/ai.ts
- src/lib/performance/apiMetrics.ts
- src/lib/sourceOfTruth.api.test.ts
- src/lib/store/useInvestigationStore.test.ts
- src/lib/store/useInvestigationStore.ts
- src/lib/store/workspace.investigation.test.ts
- src/test/aiFixtures.ts

### Modified: 59 files

- backend/app/ai/persistence.py
- backend/app/api/routes/ai.py
- backend/app/api/routes/bootstrap.py
- backend/app/mappers/dto.py
- backend/app/oem/queries.py
- src/App.tsx
- src/components/ai/AiSlot.tsx
- src/components/equipment/EquipmentDetailContent.tsx
- src/components/equipment/MiniTimelineStrip.tsx
- src/components/layout/AppShell.tsx
- src/components/layout/BrandHeader.tsx
- src/components/layout/PosteBar.tsx
- src/components/map/ZoneEditorPanel.tsx
- src/components/oem/OemConnectivityTimeline.tsx
- src/components/oem/OemDataTable.tsx
- src/components/oem/OemFilterPanel.tsx
- src/components/oem/OemReportLayout.tsx
- src/components/oem/oemViewUtils.ts
- src/components/oem/views/AnalyseCharts.tsx
- src/components/oem/views/AnomaliesTable.tsx
- src/components/oem/views/ConnectivityReport.tsx
- src/components/oem/views/ErrorCodesTable.tsx
- src/components/oem/views/IndicatorsTable.tsx
- src/components/oem/views/ParametersTable.tsx
- src/components/oem/views/PayloadSpeedFuelCharts.tsx
- src/components/oem/views/SpeedFuelCharts.tsx
- src/components/oem/views/TyreCharts.tsx
- src/components/parc/CycleStepper.tsx
- src/components/performance/PerformanceChart.tsx
- src/components/shared/DataFreshnessIndicator.tsx
- src/components/shared/PeriodFilters.tsx
- src/features/map/map.simulation.ts
- src/features/map/map.types.ts
- src/features/map/map.utils.ts
- src/lib/ai/alertIntelligence.ts
- src/lib/ai/dispatch.ts
- src/lib/ai/exceptionInvestigation.ts
- src/lib/ai/placeholders.ts
- src/lib/api/client.ts
- src/lib/api/oem.ts
- src/lib/export/performanceXlsx.ts
- src/lib/hooks/useLiveSimulation.ts
- src/lib/mock/scenarioMetrics.ts
- src/lib/mock/types.ts
- src/lib/oem/format.ts
- src/lib/oem/types.ts
- src/lib/ops/shiftWindow.test.ts
- src/lib/ops/shiftWindow.ts
- src/lib/performance/metrics.api.test.ts
- src/lib/performance/metrics.ts
- src/lib/store/useOpsStore.ts
- src/pages/ActionsIA.tsx
- src/pages/AlertesIA.tsx
- src/pages/Parametres.tsx
- src/pages/Performance.tsx
- src/pages/dev/SimulationCentre.tsx
- src/pages/oem/OemPage.tsx
- src/pages/supervision/Carte.tsx
- src/pages/supervision/Film.tsx

### Deleted (recoverable from Git): 6 files

- src/components/events/EventInspector.tsx
- src/components/exceptions/ExceptionInspector.tsx
- src/components/optimisation/BeforeAfterSim.tsx
- src/components/optimisation/ConstraintsRail.tsx
- src/components/optimisation/DispatchActionList.tsx
- src/components/optimisation/ImpactSummary.tsx
