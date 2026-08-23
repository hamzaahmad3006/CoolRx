# Deploying CoolRx to Railway

Four services: **Postgres (PostGIS)**, **Redis**, **api**, **web**. The worker
runs as a second deployment of the api image with a different start command.

Everything below has to be done from your own Railway account — creating
accounts, entering payment details and pasting API keys are yours to do, not
something to hand off.

---

## 0 · Before you start

You need:

* the repo pushed to GitHub (it is — `hamzaahmad3006/CoolRx`, `main`)
* your FortyGuard API key and Census API key
* about 20 minutes

**The demo runs in fixture mode.** `FIXTURE_MODE=true` serves every FortyGuard
response from the committed recordings, so the deployed site spends **zero API
credits** no matter how many judges open it. The keys below are only needed if
someone starts a *new* analysis from the deployed Studio page.

---

## 1 · Postgres with PostGIS

Railway's stock Postgres template does **not** include PostGIS, and the schema
will not migrate without it — `0001_initial_schema` creates geometry columns.

In the Railway dashboard:

1. **New → Database → Add PostgreSQL**
2. Open the service → **Settings → Source Image**
3. Replace the image with `postgis/postgis:16-3.4`
4. **Deploy**

Then confirm the extension is available. Railway's Postgres service has a
**Data → Query** tab:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT postgis_full_version();
```

If that second statement returns a version string, the database is ready. If it
errors, the image did not change — check step 3 rather than continuing, because
every later step will fail in a way that points somewhere else.

## 2 · Redis

**New → Database → Add Redis.** No configuration needed. It backs the job queue
only; nothing in it needs to survive a restart.

## 3 · The API

1. **New → GitHub Repo → CoolRx**
2. **Settings → Root Directory**: `backend`
3. Railway will detect the Dockerfile. Leave the builder as Dockerfile.
4. **Settings → Networking → Generate Domain** — note the URL, the web service
   needs it.

**Variables** (Settings → Variables). Railway injects the database and Redis
URLs as references, so use the reference syntax rather than pasting values:

```
DATABASE_URL      = ${{Postgres.DATABASE_URL}}
REDIS_URL         = ${{Redis.REDIS_URL}}
FIXTURE_MODE      = true
LOG_FORMAT        = json
CORS_ALLOWED_ORIGINS = https://<your-web-domain>
FORTYGUARD_API_KEY = <your key>
CENSUS_API_KEY     = <your key>
```

Two notes on `DATABASE_URL`. Railway supplies it as `postgresql://…`, and
SQLAlchemy needs the driver named: `postgresql+psycopg://…`. Set it explicitly
rather than referencing, or add a `DATABASE_URL` override of the form

```
postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}
```

`CORS_ALLOWED_ORIGINS` must be the web service's public URL. A wrong value here
produces a site that loads and then fails every request with no visible error
except in the browser console — the single most common way this deploy goes
wrong.

## 4 · Migrate and seed, once

Railway's **Deployments → ⋯ → Run Command** runs a one-off in the deployed
image. Run these three, in order:

```bash
alembic upgrade head
```
```bash
python -m scripts.load_catalog
```
```bash
python -m scripts.seed_presets
```

Then check readiness — this is the single most useful diagnostic in the project:

```
https://<your-api-domain>/api/health/ready
```

Every check should read `"state": "ok"`. `intervention_catalog` should say
`2 cited entries`. If `model_artifacts` is down, the model files did not reach
the image; if `postgis` is down, step 1 did not take.

## 5 · The worker

The pipeline runs here, not in the API. Without it, a diagnosis stays `queued`
forever and the UI spins with no error.

1. **New → GitHub Repo → CoolRx** again (same repo, second service)
2. **Root Directory**: `backend`
3. **Settings → Deploy → Custom Start Command**:
   ```
   rq worker --url "$REDIS_URL" coolrx
   ```
4. Same variables as the API. It needs the API keys for the same reason the API
   does — it is what actually calls the providers.
5. **No public domain.** It serves nothing.

## 6 · The web app

1. **New → GitHub Repo → CoolRx** (third service)
2. **Root Directory**: `frontend`
3. **Variables**:
   ```
   NEXT_PUBLIC_API_BASE_URL = https://<your-api-domain>
   NEXT_PUBLIC_USE_FIXTURES = false
   ```
4. **Generate Domain**

`NEXT_PUBLIC_*` values are inlined at build time, not read at runtime. Changing
either one requires a **redeploy**, not a restart — a restart will appear to do
nothing and cost you twenty confused minutes.

Then go back to the API service and set `CORS_ALLOWED_ORIGINS` to this domain.

---

## Verifying the deploy

In order, because each one depends on the last:

1. `https://<api>/api/health/ready` → every check `ok`
2. `https://<api>/api/projects` → three preset districts
3. `https://<api>/api/model/validation` → metrics and limitations
4. Open `https://<web>/` → three district cards
5. Click **Central Phoenix** → the map draws, legend reads about 36.8–37.1 °C
6. **Prescribe** → a plan appears within a minute or so
7. **Download PDF** → a four-page report

If step 6 hangs, the worker is not running or cannot see Redis. That is the
failure this deploy is most likely to hit, and step 5 will look perfect while
it happens.

## Notes

**Image size.** The API image is about 1.5 GB. Railway has no hard image cap on
the paid tiers, but a cold start pulls it, so the first request after a scale-to-
zero is slow. Keep the service warm during judging.

**Fixture size.** `backend/data/fixtures` is 29 MB and ships in the image on
purpose. It is what makes the deployed demo cost nothing to run and work when
FortyGuard is unavailable.

**One region.** Put every service in the same Railway region. Cross-region
database round trips turn a 3-second diagnosis into a 30-second one.
