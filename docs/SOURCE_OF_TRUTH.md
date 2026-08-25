# MinePulse — Source of Truth Matrix

Authoritative path: **PostgreSQL → `app/services/operational/` → thin DTO mappers → FastAPI → Zustand store → UI surfaces.**

Synthetic shift IDs (`shift-{db_id}`) exist **only** at the API/client boundary. Services use integer `shift_id`.

| Concept | DB table / field | Service | API | Store field | UI surfaces |
|---------|------------------|---------|-----|-------------|-------------|
| Site | `sites.code` | `context.resolve_site` | `?site_code=` on bootstrap/equipment/production | `selectedSiteId` | Film, Carte, Performance, header filters |
| Shift | `shifts.shift_id` | `context.resolve_shift` | `?shift_id=shift-N` | `selectedShiftId` | Film, Performance, production KPIs |
| Sim clock | simulator `sim_now` | `context.sim_now_utc` | `simNow` on bootstrap | `simNowIso` | Film window, OEM timeline, equipment detail |
| Equipment state | `equipment.current_state` | `equipment.build_fleet_bulk_context` | `/api/bootstrap`, `/api/equipment/live` | `equipment[].state` | Film, Carte, Fleet, Alertes |
| Position | `equipment_positions` | bulk positions | live DTO `position` (null if missing) | `equipment[].position` | Carte, Film |
| Telemetry | `equipment_telemetry` | bulk telemetry | live DTO fuel/payload/gasoil | `equipment[]` | Equipment detail, Performance fuel |
| Trips this shift | `cycles` (COMPLETED, shift-scoped) | `cycles.shift_trip_counts` | `tripsThisShift` | `equipment[].tripsThisShift` | Performance voyages, Film |
| Cycle average | `cycles.total_duration_sec` | `cycles.avg_cycle_minutes_for_equipment` / `avg_cycle_minutes_bulk` | `cycleDureeMoyenneMin` | same | Performance cycle, Parc |
| Cycle time samples | `cycles` (COMPLETED, shift-scoped) | `cycles.cycle_time_samples` | bootstrap `cycleTimeSamples` | `cycleTimeSamples` | Performance cycle histogram |
| Assignment | `equipment_assignments` | `assignments.current_assignment` | `operatorId`, `destinationZoneId` | equipment rows | Film, dispatch context |
| Production attainment | `production_targets`, `production_actuals` | `production.production_summary` (only place attainment is computed) | `/api/production`, bootstrap | `productionByShift.shiftly[0]` | PosteBar, Paramètres, Performance |
| Alerts | `alerts` | `alerts.update_alert`, `alerts.list_site_alerts` | `GET bootstrap`, `PATCH /api/alerts/{id}` | `alerts[]` | Alertes IA, Exceptions, Events |
| Zones | `zones` (PostGIS) | `zones.*` CRUD | `/api/zones` | `zones[]` | Carte (API mode writes to DB) |
| Settings | `operational_settings` (DB authoritative) | `settings.*` | `/api/settings/operational` | threshold fields | Paramètres, OEM thresholds |
| Downtime | `downtime_events`, `equipment_states` | `downtime.downtime_reasons` | bootstrap | `downtimeReasons` | Performance downtime |
| Timeline | `equipment_states` | `timeline.timeline_for_shift` | bootstrap | `timelineSegments` | Film |

## Mock mode (`VITE_USE_API=false`)

Client-side `generateMockWorld()` and `MERAH_SHIFT_SCENARIO` drive the UI. No PostgreSQL. Scenario narrative is allowed.

## API mode (`VITE_USE_API=true`)

All operational values must come from the path above. AI narrative modules return neutral “non activée” copy. Mock scenario must not appear as live ops data.

## LangGraph investigations

Investigation evidence adapters call the same `app/services/operational/*` and
`app/oem/*` functions used by the REST API. The graph orchestrates those
services and persists evidence provenance; it does not own operational rules or
execute operational actions.
