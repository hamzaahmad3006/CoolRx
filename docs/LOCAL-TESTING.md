# Running and testing CoolRx locally

Two ways to run it. Pick one.

* **Containers** — one command, closest to what gets deployed. Use this to check
  the thing a judge will see.
* **Host** — the API and web run from your shell with reload. Use this if you
  want to change code while testing.

Either way Postgres and Redis come from Docker. There is no supported path
without it.

`make` is not installed on this machine, so every recipe below is written out as
the underlying command. The Makefile has the same targets if you install it.

---

## Before anything: is Docker actually up?

Docker Desktop wedged during this session — it answered its socket but returned
nothing, and `docker images` came back empty. If that happens again, quit it from
the tray (**Quit Docker Desktop**, not just closing the window) and start it
again; a reboot if that fails.

```bash
docker ps
```

You want a table header, even with no rows. Empty output means it is still
broken and nothing below will work.

---

## Option A — containers

```bash
cd /d/CoolRx
docker compose -f infra/docker-compose.yml --profile api up -d --build
```

First build takes several minutes; after that it is cached. Then wait for ready:

```bash
curl -s http://localhost:8000/api/health/ready
```

Every check must read `"state":"ok"`. Then load the catalog and districts — the
database starts empty:

```bash
docker compose -f infra/docker-compose.yml exec -T api python -m scripts.load_catalog
docker compose -f infra/docker-compose.yml exec -T api python -m scripts.seed_presets
```

Open **http://localhost:3000**.

To stop, keeping the data:

```bash
docker compose -f infra/docker-compose.yml --profile api down
```

Add `-v` to drop the database as well and start clean.

---

## Option B — host

Four terminals. Postgres and Redis still come from Docker.

**1 · Services**

```bash
cd /d/CoolRx
docker compose -f infra/docker-compose.yml up -d db redis
```

**2 · Migrate and seed** (first run only)

```bash
cd /d/CoolRx/backend
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m scripts.load_catalog
./.venv/Scripts/python.exe -m scripts.seed_presets
```

**3 · API**

```bash
cd /d/CoolRx/backend
./.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

**4 · Worker**

```bash
cd /d/CoolRx/backend
./.venv/Scripts/rq.exe worker coolrx --url redis://localhost:6379/0 --worker-class rq.worker.SimpleWorker
```

Two details that will cost you an hour if you get them wrong. `rq` is the console
script — `python -m rq` fails, the package has no `__main__`. And
`--worker-class rq.worker.SimpleWorker` is required on Windows: RQ's default
worker calls `os.fork()`, which does not exist here, so the worker starts, takes
a job, and dies with `AttributeError` the moment one arrives. The job sits
`queued` and the UI spins forever.

**5 · Web**

```bash
cd /d/CoolRx/frontend
npx next dev -p 3000
```

`frontend/.env.local` must contain:

```
NEXT_PUBLIC_USE_FIXTURES=false
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Unset means **fixtures**, deliberately — a misconfigured deploy should still
demonstrate rather than point at a backend that is not there.

---

## The end-to-end walkthrough

Do these in order. Each depends on the last, so the first failure tells you where
the problem is.

### 1 · Backend is healthy

```bash
curl -s http://localhost:8000/api/health/ready
```

Six checks, all `ok`. `intervention_catalog` should say `2 cited entries`. If
`model_artifacts` is down the model files are missing; if `postgis` is down the
database image is wrong.

### 2 · Landing page

**http://localhost:3000** → three cards: **Downtown Las Vegas**, **Central
Phoenix**, **Central Tucson**, each about 3 sq mi, "Ready to diagnose".

If you see *Phoenix · Encanto* or a peak temperature on a card, you are running
an old build — those were invented numbers and have been removed.

### 3 · Diagnose

Click **Central Phoenix**. A diagnosis has to run once per district; if the map
is empty, start one:

```bash
curl -X POST http://localhost:8000/api/projects/<project-id>/diagnose \
  -H "Content-Type: application/json" \
  -d '{"startDate":"2025-07-15","startTime":"22:00","thresholdC":35.0}'
```

Get `<project-id>` from `curl -s http://localhost:8000/api/projects`.

It takes about a minute and finishes **`degraded`**. That is correct and not a
failure: the stated reason is `albedo_proxy, openness_proxy`, the two features
with no citable source. The pipeline names what is missing rather than inventing
it.

**What to check:**
- map draws, legend reads about **36.8 – 37.1 °C**
- statistics show mean / max / min / std, not em dashes
- the priority table lists blocks with population and person-heat-hours

### 4 · Prescribe

**Prescribe** → set a budget → **Optimize plan**. Takes a few seconds.

- 60-odd interventions, total just under budget
- every row shows a cost and a **ΔT with an interval**, e.g. `-1.6 °C (-2.0 to -1.2)`

That interval is the catalog's published range, not the model's guess. Worth
knowing when someone asks.

### 5 · Before / After

**Before/After**. Both maps draw on **one shared scale** (about 35.2–37.1 °C),
and the "predicted change" histogram is **negative** — around −1.8 to −1.6 °C.

If that histogram is positive, something regressed: it means the page is
differencing a model prediction against a measurement rather than applying the
plan's cooling.

### 6 · Action plan and PDF

Open the plan. Check the **provenance** table carries the full EPA citation,
including the caveats about incremental cost and the maintenance floor.

**Download PDF** → four pages, with the schedule, provenance, citations verbatim,
and the model's limitations. Also reachable directly:

```
http://localhost:8000/api/plans/<plan-id>/report.pdf
```

### 7 · Methods

**http://localhost:3000/methods** — the page a sceptical judge will read.

It must show **93% interval coverage** and say the ranges are *wider* than
calibrated — not that they are fine. It must list, among the limitations, that
the model does not transfer to an unseen city and that a material intervention is
predicted to do **exactly nothing** while albedo has no source.

If any of that reads reassuringly, the page is not showing live metrics.

---

## Tests

```bash
cd /d/CoolRx/backend
./.venv/Scripts/python.exe -m pytest
```

**742 passed, 0 skipped** with Postgres and Redis up — and only if the database has
been migrated and the catalog loaded, which is what the two commands in step 2 do.
Skips mean the services are not running: `conftest.py` probes the ports and skips
rather than failing, so a green run with 42 skips is not the same as a green run.

Also worth running once, because the container and CI use 3.12 while this machine
has 3.14, and the two are not interchangeable:

```bash
cd /d/CoolRx/backend
./.venv/Scripts/python.exe -m ruff check .
```

Clean. A finding here fails CI's backend job outright — it is not
`continue-on-error`, unlike mypy beside it.

```bash
cd /d/CoolRx/frontend
npx tsc --noEmit
npm run build
```

The build must succeed. It could not until `next.config.ts` was fixed, and
`next dev` does not type-check the config — so the app ran fine locally for
months while being unbuildable.

---

## Things that look broken and are not

**Diagnosis finishes `degraded`.** Correct. Two features have no citable source
and the run says so.

**`units` is null for temperature.** The FortyGuard API sends no units field for
`tcm`. Labelling it would be inventing the unit. Exceedance runs do carry `hour`
and show it.

**Every recommendation is a cool roof.** The optimiser ranks by cooling per
dollar, and at $16/m² a roof beats a $3,300 tree. That is the optimiser working.

**"Vulnerability breakdown unavailable".** SVI has no confirmed source, so the
equity quartile is null rather than estimated.

**People reached is not a whole number.** Population is a dasymetric estimate
distributed from census block groups, not a count of residents.
