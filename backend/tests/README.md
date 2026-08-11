# Backend tests

```bash
cd backend && pytest -q
```

## What runs without a database

Everything currently in this directory. The suite is deliberately built so the
invariants that matter can be tested without infrastructure:

| File | What it pins down |
|---|---|
| `test_fortyguard_validation.py` | AOI, date and parameter guards before a credit is spent |
| `test_catalog.py` | Every rejection path for an uncited or malformed catalog row |
| `test_plan_integrity.py` | Budget ceiling, interval coherence, rank uniqueness — all before any write |
| `test_job_progress.py` | Progress never regresses; a terminal status is final |

`test_plan_integrity.py` and `test_job_progress.py` use small session stubs
rather than a database. That is not a shortcut: every rule they exercise is
enforced *before* the repository touches the session, and asserting that nothing
was written on rejection is part of the test.

## What needs a live PostgreSQL + PostGIS

Not yet written. These need real SQL and belong in a separate marked suite:

- PostGIS geometry round-trips (`ST_MakeEnvelope`, `ST_AsGeoJSON`, area checks)
- `ON CONFLICT` upsert behaviour in `TileRepository` and `FgCacheRepository`
- The database `CHECK` constraints firing as the backstop for the Python guards
- `reap_stale` row counts

Bring the stack up first:

```bash
docker compose -f infra/docker-compose.yml up -d db redis
```

Then apply the schema:

```bash
cd backend && alembic upgrade head
```

## Schema verification

The declarative models in `repositories/tables.py` are the source of truth; the
`0001_initial` migration must match them. To check for drift without a database,
compile both to PostgreSQL DDL and diff the table, index and constraint names —
this is what catches a model change that was never migrated.

With a live database, `alembic revision --autogenerate` reports the same drift
directly and should produce an empty migration when the two agree.
