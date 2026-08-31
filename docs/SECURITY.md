# MinePulse — Security Boundary

## Current state (pre-AI cleanup)

MinePulse is a **development / demo** stack. The following are **not implemented**:

- User authentication (no login, JWT, or session)
- Role-based access control (RBAC)
- API key enforcement on write endpoints
- Audit log of who changed alerts, zones, or settings

## Write endpoints (unauthenticated)

| Endpoint | Risk |
|----------|------|
| `PATCH /api/alerts/{id}` | Anyone on the network can change alert status |
| `PATCH /api/settings/operational` | Threshold changes affect alert generation |
| `POST/PATCH/DELETE /api/zones` | Geometry changes affect map and simulator |
| `POST/PATCH/DELETE /api/roads` | Road geometry and OPEN/CLOSED/RESTRICTED status |

Map configuration mutations (zone create/edit/delete, road create/edit/delete, road status changes) are isolated behind:

- UI: Carte **Configurer la carte** (`configMode`) — supervision mode is read-only
- API: `/api/zones` and `/api/roads` write routes

A future `MAP_CONFIGURE` permission should wrap both the configuration-mode entry and those write endpoints. The AI, monitoring, and simulator inject paths must not call `app.services.operational.roads`.

Optional `actor_label` on alert PATCH records a human-readable label until IAM exists. It is **not verified**.

## Recommendations before production

1. Place FastAPI behind an identity-aware reverse proxy or add OAuth2/JWT middleware.
2. Restrict write routes to supervisor/regulator roles.
3. Log all mutations with `user_id`, timestamp, and before/after payload.
4. Never expose the dev simulator control API without authentication.
5. Use TLS for PostgreSQL and API traffic.

## Data classification

Operational telemetry and production data in the demo DB are **synthetic** (Merah El Ahrach simulation). Treat real deployments under your organisation's data classification policy.
