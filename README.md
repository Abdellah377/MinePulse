# MinePulse — Intelligent Mining Operations Platform

Enterprise-grade mining operations UI with a **connected data layer**: React frontend,
FastAPI backend, PostgreSQL/PostGIS, and an embedded shift simulator. The product
thesis is an **AI optimization layer** (future LangGraph) that reads Film, Carte,
Exceptions, Performance, and events together — screens are sensors and action
surfaces, not the product itself.

## Modes

| Mode | Env | Data source |
|------|-----|-------------|
| **API** | `VITE_USE_API=true` | PostgreSQL → `app/services/operational/` → REST → Zustand |
| **Mock** | default | Client `generateMockWorld()` + Merah El Ahrach scenario |

See [docs/SOURCE_OF_TRUTH.md](docs/SOURCE_OF_TRUTH.md) for the authoritative data matrix.

## What's included

- **Film / Carte / Performance / Alertes** — operational views backed by API or mock
- **OEM reporting** — connectivity, telemetry, diagnostics (7-interface layout)
- **Workspace tabs** — multi-panel analysis with persisted layout
- **Simulation Centre** — start/pause/reset/inject without a separate simulator terminal
- **Write APIs** — alert status, operational settings, zone CRUD (PostGIS in API mode)
- **AI investigation API** — bounded LangGraph evidence/diagnosis orchestration; no automatic actions

## Tech stack

- React 19 + TypeScript + Vite + Tailwind v4
- Zustand stores, MapLibre GL, Recharts
- FastAPI + SQLAlchemy 2 + GeoAlchemy2 + Alembic + LangGraph
- Embedded Python simulator (`backend/simulator/`)

## Project structure

```
src/
  components/
    ui/          reusable primitives (button, card, table, sheet, command...)
    layout/       app shell, sidebar, topbar, command palette, AI copilot
    map/          custom mine-site SVG map component
    equipment/    shared equipment detail drawer/content
    dashboard/    dashboard-only widgets
    analytics/    analytics-only chart components
    shared/       small reusable widgets (KpiCard) used across pages
  lib/
    mock/         domain types + deterministic mock data generator
    store/        Zustand stores (ops data + UI state)
    hooks/        live-simulation hook
    status.ts     shared color/icon config for equipment states & alerts
    format.ts     number/date formatting helpers
  pages/          one file per route
```

## Getting started (API mode)

One terminal starts the UI, FastAPI, and the **embedded simulator**:

```bash
npm install
cd backend && pip install -r requirements.txt && cd ..
# PostgreSQL + seed (once):
#   psql ... -f shema_postgre/minepulse_schema.sql
#   cd backend && python -m simulator seed
#   alembic stamp head
npm run dev:all
```

Then open:
- UI: http://localhost:5173
- Simulation Centre: http://localhost:5173/dev/simulation

Use **Start / Pause / Reset / Inject** in Simulation Centre — no separate
`python -m simulator run` terminal is needed.

```bash
npm run dev        # UI only (local mock if VITE_USE_API is not true)
npm run build      # production build (includes type-checking)
npm test           # vitest — API query / mapping tests
npm run lint       # oxlint
npm run preview    # preview the production build
```

## Architecture / source of truth

```
PostgreSQL → app/services/operational/ → DTO mappers → FastAPI → Zustand → UI
```

- Fresh DB from SQL dump: apply `shema_postgre/minepulse_schema.sql`, then `cd backend && alembic stamp head` (do not run `upgrade` after the dump — the schema is already present).
- Alembic is **not** a full schema: `alembic upgrade head` only creates `operational_settings` if missing. See [docs/DATABASE_SETUP.md](docs/DATABASE_SETUP.md).
- Schema check: `python backend/scripts/verify_schema.py`
- Static audit: `python backend/scripts/audit_static_data.py`
- Readiness: [docs/PRE_AI_READINESS_REPORT.md](docs/PRE_AI_READINESS_REPORT.md)

## Getting started (UI-only mock)

```bash
npm install
npm run dev
```

Then open the printed local URL (defaults to `http://localhost:5173`).

## Notes on the mock data

- Equipment, operators, zones, and routes are generated per site
  (Khouribga, Benguerir, Youssoufia) with a seeded RNG so the initial state
  is stable across reloads.
- A background tick (every ~2.2s) mutates equipment state/position/fuel to
  simulate a live feed — this drives the "Live" indicator in the topbar.
- Timeline history, cycle-time samples, downtime reasons, and maintenance
  history are all synthesized client-side; there is no persistence.
