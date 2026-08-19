# CoolRx — Remaining Tasks

Working document. Tasks are ordered by dependency, so doing them top-to-bottom
avoids writing anything twice. Each is sized to be finishable and verifiable on
its own.

**Last updated:** 2026-08-18 · **Target:** complete before 24 Aug · **Tests:** 559 collected · **524 passing, 0 failing** ·
35 need Postgres/Redis (see N-1b)

> Commit SHAs changed when history was rewritten for the initial push; see
> `git log` rather than quoting them here.

---

## Status at a glance

| Layer | Done | Remaining |
|---|---|---|
| Frontend pages | ✅ 10 of 10 + drawer | — |
| Deployment | ✅ Makefile · both Dockerfiles · CI | frontend service in compose |
| Backend persistence | ✅ complete | — |
| Backend pipeline | ✅ all modules built | raster/census providers; training on real data |
| Backend API surface | ✅ 20 routes wired | worker stages that call the pipeline |
| Local env | ✅ `.venv` + all deps install | — |
| FortyGuard API | ✅ live, authenticated, parsed | — |
| Data | ✅ fixtures (B-2) | ⚠️ catalog (B-1) still 1 of 4 rows |

**Critical path to a working demo:** B-2 is resolved — 14 real Phoenix fixtures are
committed, so the pipeline runs offline. B-1 remains: the catalog holds one row, so
the optimizer can only ever recommend street trees. After B-1, the geo providers
(Task 3) are the largest remaining code task, and model training (Task 4) depends
on them.

---

## ⚠️ Blocker that needs a human decision

### B-1 · Intervention catalog data
`backend/data/interventions_catalog.csv` ships with **zero data rows**.
SRS §11.4 deliberately supplies no unit costs or effect sizes, because inventing
plausible-looking constants would violate principle P1 at the seeding layer.

The loader, validator and AC-23 boot gate are built and tested. What is missing
is the data: each row needs `unit_cost_usd`, `delta_c_low`, `delta_c_high`,
`lifespan_years`, `maintenance_usd_yr` and a real `source_citation` from
published municipal cost data and peer-reviewed effect-size literature.

**Blocks:** Task 4 (optimizer) cannot produce a plan without it.
**Not blocked by it:** Tasks 1, 2, 3, 5, 6, 7, 8 — all proceed normally.
**Needed for:** the end-to-end demo.

Minimum viable set is four rows, one per category: `green` (street tree),
`material` (cool roof or cool pavement), `shade` (shade structure), `water`
(misting or irrigation).

- [~] Source and populate the catalog CSV — **1 of 4 rows done** (`street_tree_medium`,
      fully sourced). Still missing one row each for `material`, `shade`, `water`;
      candidates with sourced cost but unconfirmed effect size are parked in
      `backend/data/CATALOG-RESEARCH.md`
- [ ] `python -m scripts.load_catalog --dry-run` exits 0
- [ ] `python -m scripts.load_catalog` loads it and readiness reports `ok`

### ✅ B-2 · FortyGuard response fixtures — RESOLVED 2026-08-18
**14 real Phoenix responses captured and committed** (commit `a3c2871`): one `tcm`,
one `time_of_measure`, one `persistence`, and eleven `exceedance` rungs — 14 MB,
16,660 valued tiles, every file a recorded live response carrying its own
`activity_id`. `FIXTURE_MODE=true` now runs the pipeline with zero credits, and
`fixture_strict` no longer trips.

Two API discrepancies were found and fixed while doing this (see N-2). Original
note kept below for context.

---

`backend/data/fixtures/` was empty. `FIXTURE_MODE=true` is how the demo runs with zero
credits (SRS P7) and how the tests avoid spending a budget — but a fixture is a
**recorded** response, not a plausible one. Hand-writing a temperature field would
launder invented measurements into the map, which is the same P1 violation as
inventing catalog costs. So the pipeline fails loudly with no fixtures rather than
degrading to synthetic data, and `fixture_strict` defaults to `true`.

Needs a `FORTYGUARD_API_KEY` and 14 calls per district — once. Every later run is free.
Full contract in `backend/data/fixtures/README.md`.

**Blocks:** the offline demo, and any integration test of the pipeline.
**Needs first:** the `geo` module for tiling (Task 3).

- [x] `scripts/harvest_fixtures.py`
- [x] Capture Phoenix — 14/14 captured, exit 0
- [ ] Capture two more preset districts (`lasvegas`, `tucson`) — 14 calls each

---

## 🆕 Found on 2026-08-18, during live-API bring-up

These were not visible until the key arrived and the suite could actually run.

### ✅ N-1 · Tests read the real `.env` — they can spend credits — FIXED 2026-08-18
There is **no `conftest.py`**. `core/config.py:29` sets `env_file=".env"`, so a
plain `pytest` run picks up the live key and whatever `FIXTURE_MODE` happens to be
set. A full-suite run started with `FIXTURE_MODE=false` sat for 35 minutes with no
output, almost certainly polling the live API, and had to be killed. That is a real
credit-burn hazard, not a flake.

**Fix:** add `backend/tests/conftest.py` that forces `FIXTURE_MODE=true` and blanks
`FORTYGUARD_API_KEY` for the whole session, so no test can reach the network
regardless of local `.env` state.

- [x] `tests/conftest.py` pinning fixture mode + empty key — also blanks the LLM
      keys, and a session-scoped guard fails the run if anything re-enables live calls
- [x] Suite runs without touching the network: **524 passed, 0 failed**
- [ ] CI runs it with no key present at all

**Follow-on found while fixing this — N-1b.** 35 tests (`test_health` 7,
`test_job_progress` 18, `test_aoi_routes` 10) block on Postgres and Redis, which
are not running locally. This is a *different* hazard from the credit burn: the
suite hangs rather than skipping. `docker compose -f infra/docker-compose.yml up -d`
makes them runnable; better, they should skip with a clear reason when the services
are absent.

- [x] Service-dependent tests now skip cleanly — `conftest.py` probes both ports
      once per session (0.35 s socket timeout) and skips with a reason naming the
      compose command to start them. **The full suite completes in one run again:
      522 passed, 38 skipped, 0 failed.**
- [ ] Record their pass count once Postgres/Redis are running (`make services`)

### 🟡 N-2 · Live API contradicts the documented response shape — parser fixed, report outstanding
Fixed in `a3c2871`, recorded here because the docs still say otherwise:

| Documented | Actually returned | Effect before fix |
|---|---|---|
| tile value under one of `value`/`temperature`/`tcm`/… | `average_temperature` | every tile parsed with `value=None` |
| `stats_data.Temperature_stats.Mean` | `stats_data.temperature_stats.mean` | every statistic read as `None` |

Both are now read under their observed names, still with no defaulting. Worth
raising with the organisers, since the published docs are wrong.

- [x] Parser reads the observed names
- [ ] Report the discrepancy to FortyGuard (#help-technical or support@)

### N-3 · `units` is absent from every live response — AC-02 cannot pass as written
Confirmed across all 14 fixtures: `stats_data` carries **no** `units` field. The
parser correctly returns `None` rather than assuming °C. AC-02 requires units "read
from `stats_data.units`", which is currently unsatisfiable.

Hardcoding "°C" would be exactly the fabrication P1 forbids, so this needs a product
decision, not a code change:

- [ ] Decide: render unitless, or label from `analytic_type` with the assumption
      disclosed in the UI and the PDF the same way other assumptions are
- [ ] Amend AC-02 to match whichever is chosen

**Priority:** P1 — affects every number shown to a judge.

### ✅ N-4 · Backend was not installable — FIXED 2026-08-18
`pip install -e .` failed twice: `readme` pointed outside the package root, and the
flat layout had no explicit package list. Both fixed in `a3c2871`. This also
unblocks the production Dockerfile, which installs the same way.

- [x] `pyproject.toml` installs cleanly into `backend/.venv`
- [x] Full dependency stack builds on Python 3.14 (lightgbm, shap, rasterio,
      geopandas, langgraph)

### ✅ N-5 · Submission checklist is wrong in the SRS — FIXED 2026-08-18
From the official hackathon canvases (see `docs/SLACK-OFFICIAL-FINDINGS-2026-08-18.md`):

- The collaborator to add is **`Hackathon-FG` (hackathon@fortyguard.com)**. The SRS
  says `fortyguard` in eight places — the wrong handle means judges cannot open the repo.
- Submission is **four** items, not three. The missing one is a **≤500-word
  description**: problem → who it's for → endpoints used → measured result.
- The repo may stay **private**; the SRS's "make it public" step is stricter than required.

- [x] Corrected **9** `fortyguard` references in `SRS-PRD.md` to
      `Hackathon-FG` (hackathon@fortyguard.com) — one more than first counted
- [x] Added the ≤500-word description as item 4 of the §24.8 checklist, and
      restated all four items explicitly
- [x] Relaxed "repository must be public" — private plus the collaborator invite
      is what the organisers actually require
- [x] Q-16 closed: the FAQ canvas answers it

---

### ✅ N-6 · Demo harness, frontend container and CI — DONE 2026-08-18

Three deployment gaps the audit found, all closed together.

**`Makefile`** — AC-13 requires `git clone && make demo` to work with no API key.
`make demo` refuses to start if no fixtures are committed, reports how many it
found, and brings the stack up with `FIXTURE_MODE=true`. Also: `setup`, `services`,
`migrate`, `api`, `worker`, `web`, `test`, `test-fast`, `lint`, `check`,
`fixtures-plan`, `fixtures`, `train`.

**`frontend/Dockerfile`** — the backend had one, the frontend did not, so the
compose stack could not serve the UI and AC-20 had nothing to deploy. Three-stage
build, non-root runtime, healthcheck. Required `output: "standalone"` in
`next.config.ts`, which was also not set; type and lint errors now fail the
production build instead of shipping.

**`.github/workflows/ci.yml`** — three jobs. Backend runs the suite against real
Postgres and Redis service containers **with no key present**, which is AC-13
enforced rather than asserted. Frontend typechecks, builds, and greps the emitted
bundle for credential-shaped strings (AC-15). A third job fails if a `.env` is ever
tracked.

- [x] `Makefile` with `demo` as the judge entry point
- [x] `frontend/Dockerfile` + `output: "standalone"`
- [x] CI with no key available to any job
- [ ] **Not executed locally:** `make` is not installed on this machine, so the
      recipes are syntax-reviewed but unrun. First CI run will exercise them.
- [ ] Add the frontend service to `infra/docker-compose.yml` so `make demo` serves
      the UI in the same stack rather than needing `make web` alongside

---

## Phase A — API contract and wiring

### ✅ Task 1 · Pydantic request/response schemas · `backend/schemas/` — DONE
The contract every other backend task codes against, and the thing the
frontend's 21 RTK Query endpoints must agree with.

- [x] `schemas/common.py` — `Estimate`, error envelope, provenance, shared scalars, disclaimers
- [x] `schemas/projects.py` — AOI create/validate, preset list, project detail
- [x] `schemas/analytics.py` — the 4 analytic types, tile GeoJSON, features, exposure, attribution, priorities, candidates
- [x] `schemas/plans.py` — plan request/response, counterfactual, impact summary, equity
- [x] `schemas/jobs.py` — job status, stage, progress, degraded reason, SSE frame
- [x] `schemas/verification.py` — protocol, result comparison, model card
- [x] `schemas/agent.py` — node trace, guard verdict, violations
- [x] `schemas/system.py` — health, readiness, credits, coverage warning
- [x] Cross-check every field against `frontend/src/types/api.ts` — **14 mismatches found and reconciled**
- [x] `Estimate` cannot be constructed without a well-ordered interval

**Result:** 66 models, all generating valid JSON Schema. 75 new tests (207 total).
`tsc --noEmit` clean after the frontend reconciliation.

Attribution went into `analytics.py` rather than its own module — it is a per-tile
enrichment alongside features and exposure, and splitting it would have separated
three things every consumer reads together.

**The 14 mismatches.** Most were nullability, and in every case the backend was
right because the upstream data has real gaps — so the frontend types were
corrected rather than the API loosened:

| Mismatch | Resolution |
|---|---|
| `TileFeatures`, `Exposure`, `TilePriority` non-nullable | Made nullable — NLCD gaps, elevation voids, tiles outside a block group |
| `pctReachedTopSviQuartile` non-nullable | `number \| null` — not computable on sparse exposure |
| `Job.kind` missing `harvest` | Added |
| `Job.projectId` non-nullable | Nullable — a harvest job has no project |
| `Job` missing timestamps | Added `createdAt`/`updatedAt` |
| `dependencies` values missing `skipped` | Added — unchecked ≠ healthy |
| `AgentRun.guardViolations` was `string[]` | Now `GuardViolation[]` with node/token/context/reason |
| `AgentRun` token counts non-nullable | Nullable — deterministic nodes consume none |
| `TilesResponse.generatedFrom` wrapper | Flattened to `activityId`, added `nullCount` |
| `units` non-nullable | Nullable throughout — echoed from the response, not assumed |
| `hotspotCutoff`, `districtMeanC` non-nullable | Nullable until a run has values |
| `AnalyticRun.activityId` non-nullable | Nullable — fixture-backed runs have none |
| Catalog `unit` was free-text | Constrained to the 5-value union; a unit with no formatter renders dimensionless |
| `PlanTotals` missing `budgetUsd` | Added — a plan is never shown without its ceiling |

Fixing the nullability surfaced 8 real `tsc` errors in already-built pages: they
were rendering values that can legitimately be missing. Added `formatNumberMaybe`
and `formatHourOfDayMaybe`, which render an em dash rather than `0` — a zero in a
temperature column reads as a measurement.

### ✅ Task 2 · Controllers, routes and workers — DONE
- [x] `controllers/errors.py` — domain exceptions, exhaustive code → HTTP status table
- [x] `controllers/adapters.py` — every schema ↔ wire ↔ row conversion, in one place
- [x] `controllers/projects.py` — AOI validation → geodesic area → persist
- [x] `controllers/analytics.py` — tiles, stats, attribution, exposure, priorities
- [x] `controllers/diagnose.py` — validate, guard, enqueue
- [x] `controllers/prescribe.py` — plan requests and plan reads with totals re-check
- [x] `controllers/jobs.py` — status reads + SSE stream
- [x] `controllers/catalog.py` — catalog reads (no write path, by design)
- [x] `optimizer/priorities.py` — ranking, computable today from persisted data
- [x] `routes/` — 18 paths, `/api` prefix, no business logic in any handler
- [x] `workers/` — RQ queue, job entry points, enqueue boundary, stale-job reaper
- [x] `middleware/` — error envelope, rate limit, demo-key gate
- [x] 40 schemas in the generated OpenAPI

**Result:** 289 tests passing, up from 207.

**Three bugs worth recording:**

1. **Exceptions raised inside `BaseHTTPMiddleware` never reach FastAPI's exception
   handlers.** Starlette runs `BaseHTTPMiddleware` outside the layer that dispatches
   them, so a raise escapes as an unhandled 500. Rate-limited requests would have
   returned "something went wrong" instead of "slow down", and the demo-key gate
   would have 500'd instead of 401'd. Middleware now *returns* the envelope.
2. **`dependency_overrides` cannot reach middleware.** The demo-key gate called
   `get_settings()` directly, so the test overriding it silently exercised the real
   environment and reported the gate working when it had never run. Settings are now
   injected at construction.
3. **The credit guard compared two different units** — a per-day submission count
   against a credit-balance floor (200 vs 50,000), which would have refused *every*
   live diagnosis. The submission cap is now checked locally; the credit reserve
   stays inside the client, which is the only layer that can see the balance.

Also: `field: str | None` on the error dataclass shadowed `dataclasses.field` inside
the class body, which crashed at import; and the AOI test fixture was 11.94 mi²
against a 10 mi² cap — the validator was right, my arithmetic wasn't.

**What does not work yet, and why.** `POST /diagnose` and `POST /plans` accept,
validate, guard, enqueue and report progress — then fail with a message naming the
missing module. The pipeline stages need `geo`, `ml` and `optimizer` (Tasks 3–5).
The alternative was synthesising temperature data to make the flow appear to work,
which would put invented numbers in front of the person evaluating the tool.

**Second data dependency discovered:** `data/fixtures/` is empty, and fixtures must be
**captured** from the live API, not written. See `backend/data/fixtures/README.md` —
hand-writing a temperature field is the same P1 violation as inventing catalog costs.
14 calls per district, 3 districts, one time. Tracked as blocker B-2 below.

---

## Phase B — The pipeline (bottom-up, each usable alone)

### ✅ Task 3 · `backend/geo/` — tiling and feature enrichment — DONE
- [x] Tile grid generation from an AOI at 60/80/100 m
- [x] Stable `tile_key` (geohash of centroid) so one ground location keeps one key
- [x] Provider contract with per-provider native resolution and vintage
- [x] Enrichment merge that guarantees null-never-becomes-zero
- [x] Coverage reporting per field
- [ ] NLCD raster provider — needs rasterio + the NLCD tiles (see below)
- [ ] Terrain provider — needs elevation rasters
- [ ] Census dasymetric population + SVI join — needs the Census API

**The grid is built in UTM, not in degrees.** A degree grid has cells whose width
changes with latitude, so a "60 m" tile would be 60 m tall and something else wide,
and person-heat-hours — population × hours summed over tiles — would be computed
over cells of unequal area. Snapping to a multiple of the granularity in UTM also
makes the grid globally deterministic, so **two overlapping projects share tile keys
for shared ground** and enrichment can be reused rather than recomputed per AOI.
There's a test asserting exactly that.

Precision-9 geohash, deliberately: precision 8 is 38 m × 19 m, and two neighbouring
60 m centroids could share one cell along the narrow axis — silently merging two
places into one row.

**Raster/network providers are stubs by design, not by omission.** Each is imported
inside a try/except and replaced with an `UnavailableProvider` that returns explicit
nulls and a named reason. The run completes with an honest empty column rather than
crashing or — worse — quietly dropping the field so downstream code defaults it.
Wiring the real NLCD/terrain/census sources needs rasterio + GDAL, which is the
Python 3.14 dependency risk already flagged.

50 tests, including a geodesic check that cells really are the requested size.

### ✅ Task 4 · `backend/ml/` — model and attribution — DONE
- [x] Ordered feature contract, verified against the saved artefact on load
- [x] LightGBM quantile models at p10 / p50 / p90
- [x] Held-out metrics: MAE, R², interval coverage
- [x] TreeSHAP per-tile attribution
- [x] Out-of-support detection (reject rather than extrapolate)
- [x] Counterfactual transforms per intervention category
- [ ] Training on real data — B-2 fixtures now exist; still blocked on the Task 3
      providers, since a model trained on geometry-only features gives no useful
      SHAP attribution (FR-011) and no honest metrics panel (FR-025)

43 tests, including a real model trained on synthetic data with a known structure,
so the tests assert it *recovered the relationship* rather than merely returned
numbers.

**Three quantile models, not one plus a residual spread.** A constant interval
assumes uncertainty is uniform across the feature space, and it is not — a dense
surveyed downtown block is predicted far more confidently than a sparse industrial
edge. Learning the interval is what makes `interval_coverage` a meaningful check.

**Feature order is part of the model.** A reordered vector does not fail; it returns
confident, plausible, wrong predictions that nothing downstream can detect. So the
order is saved with every artefact and verified on load — there's a test that
tampers with the saved order and asserts the load raises.

**Extrapolation is refused, not answered.** A quantile model's interval does *not*
widen outside its training range; it reports the same narrow band it learnt inside,
so an extrapolated prediction looks exactly as confident as a supported one.

Missing values pass through as NaN, never imputed. LightGBM learns a default split
direction for NaN, which beats substituting a mean — the mean is a fabricated
observation asserting a tile has average canopy when nobody measured it.

**No `shap` dependency needed:** LightGBM's `pred_contrib=True` *is* exact TreeSHAP,
computed in-library.

### ✅ Task 5 · `backend/optimizer/` — the exceedance ladder and plan search — DONE
- [x] Exceedance ladder: hours-above-threshold curve at T…T+10 °C
- [x] Δhours = ladder(T) − ladder(T+|ΔT|), with linear interpolation between rungs
- [x] Person-heat-hours = population × hours; `None` when population is unknown
- [x] Equity weighting `PHH × (1 + λ·SVI)`, λ supplied by the caller
- [x] Catalog-based ΔT estimator, with the model estimator pluggable behind it
- [x] Clamp ΔT — and its interval — to the cited `[delta_c_low, delta_c_high]`
- [x] Greedy marginal-benefit-per-dollar selection under the budget
- [x] Feasibility rules per tile, with the exclusion reason returned
- [x] Area-weighted district mean, diluted by untreated tiles

47 tests. Runs today without B-1 or Task 4, because **ΔT comes from the catalog's
cited effect range** — the midpoint as the estimate, the published range as the
interval. That is not a stopgap: a cited effect size from published literature is a
legitimate, traceable planning input satisfying P1 and P2 exactly as a model
prediction would. The model estimator refines it per-tile later.

Decisions worth knowing:
- **A missing ladder rung means no ladder for that tile**, not an interpolated one.
  Filling the gap would put a fabricated measurement where a real one is absent, and
  every figure downstream would inherit it undetectably.
- **Non-monotonic rungs are clamped and logged.** Hours cannot rise with threshold;
  propagating that artefact yields a *negative* hours-avoided figure showing an
  intervention making things worse.
- **Cooling beyond the ladder's top rung is refused**, not extrapolated.
- **One intervention per tile.** Stacking would double count — the ladder converts a
  single ΔT, not a sum of overlapping effects nobody measured.
- **Greedy, deliberately.** ΔT spans a factor of several; optimising exactly against
  numbers that soft is false precision, and every pick is explainable in a sentence.

### 🟡 Task 6 · `backend/agent/` — numeric guard DONE, graph remaining
- [x] `numeric_guard`: deterministic extraction + set-membership check
- [x] Retry-on-violation, then fail closed to the number-free template
- [x] Adversarial test battery (43 tests)
- [x] LangGraph, 5 nodes only
- [x] Node trace, guard verdict and violations produced for `agent_runs`
- [x] Model boundary as an interface, with a scripted double for tests
- [ ] Persisting the run to `agent_runs` (needs the plan worker stage)

18 more tests. Three of the five nodes are deterministic and **every number the
reader sees comes from those three**; the guard sits between the two LLM nodes, so
prose that invented a figure never reaches composition.

The scripted client exists so a model that *does* fabricate can be provoked on
demand — a real API will not misbehave reliably, and those are the paths that
matter. One test drops every rationale and asserts the run still completes with a
verdict, a trace and its violations: that is the "language model is not
load-bearing" claim, tested directly rather than asserted.

Retries once, then fails closed. A model that invents a figure twice will invent it
a third time, and each attempt costs tokens and demo seconds.

The guard is the load-bearing half and is complete and independently testable, so
it landed first. It contains no LLM calls on purpose — it can therefore be tested
exhaustively and cheaply, and cannot fail because a network call did.

**Bypasses it catches**, each with a test:

| Bypass | Example |
|---|---|
| Spelled-out numbers | "twenty trees" when 12 was supplied |
| Rounding | "about 2 degrees" when -1.9 was supplied |
| Unit conversion | "3.42 °F" from -1.9 °C |
| Percentage rescaling | "40%" from 0.4 |
| Derived arithmetic | "12 × 450 totals 5400" when only 12 and 450 were given |
| Ordinals | "the 3rd hottest block" |

Spelled-out numbers matter most: a digit-only regex is trivially bypassed by writing
"twelve" instead of "12", and a model told to vary its phrasing does this unprompted.

Comparison is **strict equality after parsing** — formatting is not transformation
("1,234.5" == "1234.5"), but 1.9 does not admit 2. Model versions like
`lgbm-2026.08.1` are masked with a length-preserving replacement so their digits
aren't read as claims while nearby real violations are still caught.

### ✅ Task 7 · `backend/report/` — the Cooling Action Plan PDF — DONE
- [x] Report renderer with the provenance table
- [x] Every headline figure checked against a provenance record before printing
- [x] Citation appendix reproduced verbatim from the catalog
- [x] Measurement/verification protocol section
- [x] Limitations section
- [ ] Wiring to `verify_totals` (needs the plan worker stage)

16 tests, most of them **refusals**. A PDF is forwarded, printed and quoted months
later with no route back to the system that made it, so the failures worth guarding
are the ones that produce a *usable-looking* document nobody can check: a headline
figure with no provenance entry, a costed plan with no citations, a missing
disclaimer. Each raises rather than emitting.

Figures arrive **pre-formatted as strings**, never as floats. The report prints the
same text the UI showed, so the PDF and the screen cannot diverge through separate
rounding.

The rendering tests decode the real compressed streams — reportlab does ASCII85
then Flate — and assert the disclaimer, the intervals, the activity id and the
citation genuinely reach the page rather than merely reaching the builder.

**Switched weasyprint → reportlab.** weasyprint renders through Pango and Cairo,
which on Windows needs GTK system libraries installed separately — that would break
`pip install` for anyone cloning the repo.

---

## Phase C — Remaining frontend screens

Pattern for each, already proven on the 4 built pages:
`<Screen>Page.tsx` (UI only) + `use<Screen>.ts` (all logic) + thin `src/app` route
+ optional fixture. All tokens from `constants/`, all types from `types/`, no
`any` or `unknown`.

### ✅ Task 8 · Attribution drawer (SRS screen #4) — DONE
- [x] SHAP waterfall chart
- [x] Land-cover donut
- [x] Exposure summary for the selected tile
- [x] Wired into Diagnosis; Escape and scrim both close it
- [ ] Provenance link for the tile's source analytic run (needs the provenance endpoint)

Verified in the browser, not just typechecked — clicking a priority row opens it,
all four sections render, Escape closes it, and the console is clean.

Two bugs the browser caught that `tsc` could not:
- **SVI 0.81 rendered as "1".** The shared `count` precision is 0 decimals, and SVI
  is a 0–1 index, so high vulnerability displayed as maximum vulnerability.
- **Distance to water rendered as `1,840` with no unit.**

The donut draws its unmeasured remainder as a hatched arc rather than normalising
the slices to 100%. Normalising would invent composition data — the fixture keeps
`buildingPct` null precisely so that path is exercised on every open.

### ✅ Task 9 · AOI Studio (SRS screen #2) · `/studio` — DONE
- [x] Click-to-place AOI box with a size slider
- [x] Live geodesic area badge against the plan cap
- [x] Date / hour / granularity / threshold pickers
- [x] Client-side pre-validation mirroring the backend guards
- [x] Credit and block-count preview before submit
- [x] Linked from Landing — it was otherwise reachable only by typing the URL

**Two sources of truth for area, handled explicitly.** The local check uses a
spherical approximation for instant feedback on every slider move; the server
re-checks on the WGS84 ellipsoid once it settles and its answer replaces the local
one. Near the cap they can disagree, so while the server has not answered the page
says the figure is an estimate rather than claiming a verdict.

Click-to-place plus a slider rather than corner handles: the API takes a
capped-area bounding box, so position and size are the only meaningful degrees of
freedom — handles would let a user build a long thin sliver that satisfies the cap
while being useless as a district.

Does **not** use `AppShell`: the Studio runs before a project exists, and the rail
builds per-project links, so it would emit `/p//diagnose`.

### ✅ Task 10 · Cooling Action Plan (SRS screen #8) · `/plans/[id]` — DONE
- [x] Report preview, print-ready
- [x] Plan table with per-item intervals
- [x] Download action (browser print to PDF)
- [x] Spend rollup by intervention category
- [x] Measurement plan section linking to Verify
- [x] Provenance table with FortyGuard activity ids

Prints the same DOM the reader just reviewed rather than rendering a separate
server-side template. A second rendering path is a second thing that can disagree
with the first, and the report's entire claim is that every figure traces to one
source.

Items whose rationale the guard rejected are **counted and explained** rather than
silently appearing without prose — a dropped rationale means the mechanism caught
the model inventing a figure, which is worth saying.

### ✅ Task 11 · Agent Trace + Methods (SRS screen #10) — DONE
- [x] Node-by-node execution log, each labelled deterministic or language-model
- [x] Guard verdict and violations, shown not hidden
- [x] Model validation metrics with an interval-coverage callout
- [x] Limitations, in two lists

The trace fixture shows a run where the guard **caught a violation and retried**,
not a clean one. A page that only ever displays "pass" proves nothing — the reason
it exists is to show the mechanism firing, and a reader can only judge that by
seeing it. The offending token is shown with its surrounding sentence, because the
token alone cannot distinguish an invented figure from a reformatted allowed one.

Interval coverage gets its own callout: it is the number that decides whether every
other interval on the site can be believed. Below ~80% the page says the ranges are
narrower than the real uncertainty rather than presenting them as calibrated.

Limitations are split into methodology caveats (permanent) and model-card caveats
(version-specific). Merging them would let a version bump quietly drop a permanent one.

### ✅ Task 12 · Impact & Equity (SRS screen #7) · `/p/[id]/equity` — DONE
- [x] Vulnerable-group breakdown
- [x] Person-heat-hours avoided by SVI decile
- [x] λ slider with the policy-choice caveat beside it
- [x] SVI tract-resolution caveat displayed, not buried

The headline is a **comparison, not a number**: share of benefit reaching the most
vulnerable deciles set against their share of the population. "63% of benefit
reaches vulnerable areas" sounds impressive and means nothing until you know they
are 36% of the district — which is what makes the plan demonstrably progressive.

Deciles receiving *zero* benefit are called out in prose. A bar chart renders zero
as an invisible sliver, and "no block there was cost-effective enough within the
budget" is a real planning fact a reader needs.

### ✅ Task 13 · Verify (SRS screen #9) · `/plans/[id]/verify` — DONE
- [x] Protocol display, with the pre-commitment argument stated
- [x] Re-measure trigger
- [x] Predicted vs observed with the control comparison
- [x] "Within the predicted range" verdict — never "the plan worked"

The difference-in-differences is shown **decomposed**, not as one figure. Showing
only the result asks the reader to trust that controls were subtracted; showing
both changes lets them check it. Verified in-browser that the displayed −3.1 °C
recomputes exactly from the four temperatures above it.

The weather component gets its own callout: the controls warmed 0.6 °C with no
intervention, so without subtracting them the plan would appear to have delivered
2.5 °C instead of 1.9 °C. That 0.6 °C is precisely what a naive before/after would
have credited to the intervention.

### Task 14 · Not in the SRS screen table — decide before building
Two Stitch pages exist as empty folders with no SRS screen behind them:

- [ ] `features/Auth/` — the SRS specifies no authentication. **Recommend: drop.**
      A hackathon demo with a login wall costs judges time and adds no points.
- [ ] `features/CityPortfolio/` — multi-project view. **Recommend: defer to P2.**
      Only earns its place if there is time after Phase B.

---

## Phase D — Delivery

### Task 15 · Reproducibility and the repo as a deliverable (SRS P7)
- [ ] `FIXTURE_MODE` produces the full demo with zero API credits
- [ ] README: setup, run, and the honest limitations section
- [ ] `docker compose up` brings the whole stack up from clean
- [ ] Seed script for the three preset districts

### Task 16 · Verification passes
- [ ] Live PostgreSQL + PostGIS integration tests (see `backend/tests/README.md`)
- [ ] `alembic revision --autogenerate` produces an empty diff
- [ ] `tsc --noEmit` clean; no `any`/`unknown` without a documented reason
- [ ] Confirm the FortyGuard API key never reaches the browser bundle
- [ ] Lighthouse/perf check on the ~7,200-tile map

### Task 17 · Demo
- [ ] 3-minute script tied to the judging weights (Impact 40 / Execution 35 / Innovation 15 / Communication 10)
- [ ] Rehearse the degraded path — P5 says the demo cannot break

---

## Notes carried forward

- **Open question never answered:** whether to regenerate the Diagnosis page in
  Stitch. Built from the SRS spec instead; it will reconcile cleanly if
  regenerated later.
- **`uv` install / Python 3.12 pin:** never run. Verification currently uses a
  throwaway venv on Python 3.14. `pydantic` and `pyproj` install fine there; the
  real risk is narrower — GDAL, rasterio and lightgbm, which Task 3 and Task 4
  will hit first.
- **Toronto/Montreal coverage gap:** the US pre-filter accepts them and cannot be
  fixed with a rectangle. Documented and asserted in a test rather than left as
  an unexamined assumption.
