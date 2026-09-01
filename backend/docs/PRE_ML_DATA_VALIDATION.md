# Pre-ML data validation audit

`python -m scripts.audit_pre_ml_data` is a read-only report generator for a
disposable PostgreSQL database. It does not seed, reset, migrate, create, drop,
train, tune, save ML artifacts, or alter the configured MinePulse database.

The audit URL is always mandatory. Before it opens a connection, the command
requires a PostgreSQL database whose name begins with `minepulse_audit_` and
rejects the configured MinePulse database target. Credentials are ignored when
comparing targets, so changing only a username, password, or PostgreSQL driver
does not bypass the protection.

## Recommended managed multi-seed audit

From `backend/`, this command creates a uniquely prefixed database on the same
local PostgreSQL server as the configured MinePulse database, migrates only the
new database, generates each seed sequentially, writes the report outside the
database, and drops the exact disposable database in a `finally` block:

```powershell
python -m scripts.run_pre_ml_multiseed --seed 42 --seed 43 --seed 44 --target-cycles 500 --output ..\reports\pre_ml_multi_seed.json
```

The normal `minepulse_db` target is rejected by name/host/port comparison and
is never passed to Alembic or the simulator. Monitoring is disabled for the
generation subprocesses. The command never invokes a training function and
never writes model artifacts.

## Prepare one database per seed manually

Run database lifecycle commands outside the audit module. The commands below
are PowerShell examples; replace the host, user, password, and seed values.

```powershell
$AuditDb = "minepulse_audit_20260901_seed_42"
$AuditUrl = "postgresql+psycopg://postgres:REPLACE_ME@localhost:5432/$AuditDb"
createdb -h localhost -U postgres $AuditDb

$env:DB_HOST = "localhost"
$env:DB_PORT = "5432"
$env:DB_USER = "postgres"
$env:DB_PASSWORD = "REPLACE_ME"
$env:DB_NAME = $AuditDb
alembic upgrade head
python -m simulator generate-cycles --seed 42 --target-cycles 1000 --with-failures
```

Confirm that `$AuditDb` is the exact intended disposable database before each
command. Do not point those environment variables at the normal MinePulse
database. Repeat the process with a new `minepulse_audit_...` name for every
seed; the audit records the seed supplied to it but never performs generation.

## Run the audit

From `backend/`, run:

```powershell
python -m scripts.audit_pre_ml_data --database-url $AuditUrl --seed 42 --output ..\reports\pre_ml_seed_42.json
```

For a multi-seed comparison, bind each seed to its own database URL rather
than replaying different seed labels against one database:

```powershell
python -m scripts.audit_pre_ml_data `
  --seed-database "42=postgresql+psycopg://postgres:REPLACE_ME@localhost:5432/minepulse_audit_20260901_seed_42" `
  --seed-database "43=postgresql+psycopg://postgres:REPLACE_ME@localhost:5432/minepulse_audit_20260901_seed_43" `
  --output ..\reports\pre_ml_multi_seed.json
```

The optional `--artifacts-root` must contain already-saved
`failure_risk/` and `cycle_time/` artifacts. The audit only loads those
artifacts and invokes prediction/baseline methods. A missing artifact is
reported as `artifact_not_found`; the audit never trains a replacement or
writes an artifact. `--output` is an explicit JSON report path, not an ML
artifact path.

Each report includes a canonical SHA-256 digest and a `sequence_fingerprint`.
The fingerprint covers operational counts, distributions, labels, and splits,
but not surrogate primary keys or artifact filesystem paths. Re-running the
same seed should reproduce that fingerprint even if PostgreSQL serials moved.
Different seeds should differ in the fingerprint and quality sections.

The managed runner generates the first seed twice before the remaining seeds
and records `reproducibility.same_sequence`. Saved artifacts are compared to
the current snapshot through `snapshot_alignment`; a mismatch is reported and
does not trigger retraining.

## What is checked

The report uses the existing read-only ML snapshots and feature builders to
record operational counts, state/cycle distributions, duplicate keys,
missingness, constant features, cycle/state lifecycle anomalies, failure-risk
labels and splits, precursor coverage, and cycle-time targets/splits. It also
evaluates only saved artifacts and saved deterministic baselines.

The report actively rejects simulator-only scenario and hidden-truth fields.
It contains no causal scenario IDs, ground truth, or developer-only scenario
summaries.

## Tear down safely

After all simulator, Alembic, and audit sessions have exited, drop only the
exact disposable database created above:

```powershell
dropdb -h localhost -U postgres $AuditDb
```

Keep the JSON report outside that database. The read-only
`python -m scripts.audit_pre_ml_data` command never creates or drops a
database. The managed runner `python -m scripts.run_pre_ml_multiseed` does
drop the exact disposable `minepulse_audit_...` database it created, in a
`finally` block, and never drops the configured MinePulse database.
