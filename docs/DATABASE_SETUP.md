# Database setup (PostgreSQL + Alembic)

MinePulse **does not** create its operational schema via Alembic.

The Alembic revisions in this repo only add incremental MinePulse tables
(`operational_settings`, `ai_investigations`, and investigation trigger-data
normalization). Running `alembic upgrade
head` on an empty database does not create sites, equipment, cycles,
production, or PostGIS geometry. That is not a MinePulse install.

## Fresh install (the only valid empty-database path)

1. Create database and role (PostGIS required).
2. Apply `shema_postgre/minepulse_schema.sql` (includes `operational_settings`).
3. Seed: `cd backend && python -m simulator seed`
4. Stamp Alembic so revision history matches the dump **without running DDL**:

```bash
cd backend
alembic stamp head
```

Do **not** run `alembic upgrade head` after the dump. The schema is already
present; upgrade would be a no-op for `operational_settings` and still would
not create the rest of the schema.

## Existing database (schema already applied, Alembic unstamped)

```bash
cd backend
alembic stamp head
```

## What `alembic upgrade head` actually does

For an existing operational database, migrations create missing incremental
tables (`operational_settings`, then `ai_investigations`). Revisions are no-ops
when their target table already exists; the following data migration separates
the operational trigger type from the mechanism that started older
investigations. They never create the full MinePulse schema.

The development launchers (`npm run dev:all` and `npm run dev:api`) apply these
incremental migrations before starting FastAPI. If migration fails, startup
stops instead of allowing monitoring to repeatedly query a stale schema.

## Tests

Integration tests skip when PostgreSQL is unreachable. Set connection settings
(`.env` / `DATABASE_URL` components) to a disposable test database before:

```bash
cd backend && python -m pytest tests/ -q
```

Round-trip tests that mutate alerts delete their own rows.

## Verify schema

```bash
cd backend && python scripts/verify_schema.py
```

Expected tables and critical incremental columns are listed in
`backend/scripts/__init__.py` (`EXPECTED_TABLES` and `EXPECTED_COLUMNS`).
