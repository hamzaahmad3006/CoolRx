# CoolRx

**Prescription-grade urban cooling intelligence.**

CoolRx reads hyperlocal street-level temperature data, finds the blocks that are
dangerously hot, explains why, prescribes what to build under a budget, predicts the
temperature reduction with an uncertainty range, and produces a procurement-ready
Cooling Action Plan — with a pre-registered protocol to verify it worked.

Built for **FortyGuard Hackathon '26 — "Building the World's Temperature AI"**.

---

## The idea in one paragraph

A heat map tells a city *where* it is hot. It does not tell them what to build, what
it will cost, or how many hours of dangerous heat it will remove. CoolRx closes that
gap with the **exceedance ladder**: FortyGuard's `exceedance` analytic is queried at
eleven thresholds, T through T+10 °C, producing a measured curve of
hours-above-threshold per block. A predicted cooling of ΔT is then read off that same
curve at T + |ΔT|. A temperature change becomes an *exposure* change — hours of
dangerous heat avoided — using the API's own measurements rather than a model of ours.
Multiply by population and you have person-heat-hours, which is a unit a public-health
officer already reasons in. Degrees are not.

```
Measure → Diagnose → Understand → Prioritize → Prescribe → Optimize → Quantify → Report → Verify
```

---

## Quick start

Everything runs offline against committed fixtures. No API key needed to look around.

```bash
docker compose -f infra/docker-compose.yml --profile api up -d
```

That brings up PostgreSQL + PostGIS, Redis, applies the schema, and starts the API and
worker. Then:

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>. The API is on <http://localhost:8000/api/docs>.

To run the backend on the host instead (faster edit-reload, but you need the
geospatial stack locally):

```bash
docker compose -f infra/docker-compose.yml up -d
cd backend && uv sync && alembic upgrade head && uvicorn main:app --reload
```

### Tests

```bash
cd backend && pytest -q
```

530 tests, no database or network required. `cd frontend && npx tsc --noEmit` for the
type check.

---

## What is honest about this project

Three rules are enforced in code, not in documentation. They are the reason the
architecture looks the way it does.

### 1. No number originates from a language model

Every figure comes from the FortyGuard API, the database, the trained model, or
deterministic Python. The LLM receives numbers as structured input and writes
sentences around them.

That is a promise, and a promise about a language model is worth nothing without a
mechanism. `agent/numeric_guard.py` extracts every numeral from generated prose and
checks it against the exact set of values the model was handed. Strict equality after
parsing — `1,234.5` and `1234.5` are one value, but **1.9 does not admit 2**, because
a rounded figure is one nobody can trace back to a stored value.

It catches spelled-out numbers ("twenty" when 12 was supplied), unit conversions,
percentage rescaling, ordinals, and arithmetic the model performed on values it was
legitimately given. Violations trigger one retry, then the prose is dropped entirely —
`rationale` is nullable in the database precisely so the model is not load-bearing.
Delete every word it wrote and the plan is still complete.

The **Agent Trace** page shows the verdict whatever it is. A caught violation is
displayed with its offending token and surrounding sentence, because that is the
mechanism working.

### 2. Missing data is never zero

A null tile means the API returned no measurement. It is never coerced to 0 — that
would put a fabricated reading of zero degrees on a map. The same rule runs through
enrichment (a provider that has no data returns `None`, never an imputed mean), the
model (missing features pass to LightGBM as NaN), and the UI (an em dash, never a
digit).

Where a whole dataset is unavailable, the pipeline **degrades and says so**. A job can
end `completed`, `degraded` or `failed`, and the degraded reason is shown to the user
rather than presenting a gap as a complete result.

### 3. Every prediction carries its interval

`Estimate` requires `ciLow` and `ciHigh`. A bare point estimate is unrepresentable —
in the TypeScript type, in the Pydantic schema, and in the database, where CHECK
constraints reject an unordered interval. Three independent layers, because SRS §20.3
forbids ever displaying a prediction without its uncertainty.

The model learns the interval rather than assuming one: three LightGBM quantile models
at p10/p50/p90, not one plus a constant residual spread. A dense surveyed downtown
block is predicted far more confidently than a sparse industrial edge, and a constant
band would understate uncertainty exactly where a planner most needs to see it.
Extrapolation is **refused**, not answered, because a quantile model's band does not
widen helpfully outside its training range.

### And: no causal claims

Verification reports "the observed change fell **within the predicted range**", never
"the plan worked". The difference-in-differences arithmetic is shown decomposed, so a
reader can check that control blocks were subtracted rather than trusting that they
were.

---

## Repository layout

```
backend/
  clients/fortyguard/   Async-activity API client: cache → fixture → guards → submit
  geo/                  UTM tile grid, stable geohash keys, feature providers
  ml/                   Quantile models, TreeSHAP attribution, counterfactuals
  optimizer/            Exceedance ladder, priorities, budget-constrained selection
  agent/                Numeric guard + 5-node LangGraph narration
  report/               Cooling Action Plan PDF
  repositories/         The only layer holding SQL
  controllers/          Business logic; no HTTP, no SQL
  routes/               18 endpoints; no business logic
  workers/              RQ tasks and the two pipelines
frontend/src/
  features/<Screen>/    <Screen>Page.tsx (UI) + use<Screen>.ts (all logic)
  components/           Shared UI, charts, map
  constants/            Every colour, dimension, string — nothing hardcoded in a page
  types/                Domain, API, Redux types. No `any`, no `unknown`
```

**Layering rule** (SRS §16.1): routes → controllers → repositories. Routers hold no
business logic, controllers hold no SQL, repositories hold no HTTP.

---

## Status

All ten SRS screens are built. Every backend pipeline module exists and is tested.

| Area | State |
|---|---|
| Frontend | ✅ 10/10 screens + attribution drawer |
| API | ✅ 18 endpoints, one error envelope, OpenAPI at `/api/docs` |
| Persistence | ✅ 13 tables, PostGIS, Alembic baseline |
| Pipeline | ✅ geo, ml, optimizer, agent, report — all wired into the workers |
| Tests | ✅ 530 backend, `tsc` clean |

### What needs data, not code

Two things cannot be resolved by writing code, and both are deliberate:

**Intervention catalog.** `backend/data/interventions_catalog.csv` ships with **no data
rows**. Every unit cost and effect size must carry a real citation, enforced by a
database CHECK, a loader validator, and a startup gate that refuses to boot without
one. Inventing plausible constants would violate the project's central rule at the
seeding layer. Populate it, then:

```bash
cd backend && python -m scripts.load_catalog
```

**FortyGuard fixtures.** `backend/data/fixtures/` is empty. A fixture is a *recorded*
response, never a hand-written one — a fabricated temperature field would launder
invented measurements into every figure downstream. Capturing costs 14 calls per
district, once:

```bash
cd backend && python -m scripts.harvest_fixtures --district phoenix --dry-run
```

Drop `--dry-run` with `FORTYGUARD_API_KEY` set and `FIXTURE_MODE=false` to capture.

---

## Design decisions worth knowing

**The tile grid is built in UTM, not degrees.** A degree grid has cells whose width
changes with latitude, so a "60 m" tile would be 60 m tall and something else wide, and
person-heat-hours summed over unequal cells would be wrong. Snapping to a multiple of
the granularity also makes the grid globally deterministic, so two overlapping projects
share tile keys for shared ground.

**Tile keys are precision-9 geohashes of the centroid.** Precision 8 is 38 m × 19 m —
two neighbouring 60 m centroids could share one cell and silently merge two places into
one row.

**Selection is greedy on benefit-per-dollar, deliberately.** ΔT spans a factor of
several, so optimising exactly against numbers that soft is false precision. Every pick
is explainable in one sentence, and the criterion is stored per item so the ranking can
be audited.

**One intervention per tile.** Stacking would double count: the ladder converts a single
ΔT, not a sum of overlapping physical effects whose interaction nobody measured.

**Credits are protected by four independent guards** — pre-flight validation, a
concurrency check, a local daily submission cap, and the client's credit reserve. A
rejected request costs nothing, and the cache means a repeated one is free.

---

## Documentation

- [`SRS-PRD.md`](SRS-PRD.md) — full specification, 36 sections + 10 ADRs
- [`Remaining Task.md`](Remaining%20Task.md) — task ledger with decisions and findings
- [`backend/tests/README.md`](backend/tests/README.md) — what runs without infrastructure
- [`backend/data/fixtures/README.md`](backend/data/fixtures/README.md) — the fixture contract

## License

MIT.
