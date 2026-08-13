# CoolRx — Remaining Tasks

Working document. Tasks are ordered by dependency, so doing them top-to-bottom
avoids writing anything twice. Each is sized to be finishable and verifiable on
its own.

**Last updated:** 2026-08-13 · **Branch:** `feature/geo-guard-attribution` · **Tests:** 382 passing

> Commit SHAs changed when history was rewritten for the initial push; see
> `git log` rather than quoting them here.

---

## Status at a glance

| Layer | Done | Remaining |
|---|---|---|
| Frontend pages | 4 of 10 + drawer | 6 screens |
| Backend persistence | ✅ complete | — |
| Backend pipeline | geo grid, priorities, numeric guard | raster/census providers, `ml`, `optimizer`, agent graph, `report` |
| Backend API surface | ✅ 18 routes wired | — |
| Data | — | ⚠️ catalog (B-1) and fixtures (B-2) |

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

- [ ] Source and populate the catalog CSV
- [ ] `python -m scripts.load_catalog --dry-run` exits 0
- [ ] `python -m scripts.load_catalog` loads it and readiness reports `ok`

### B-2 · FortyGuard response fixtures
`backend/data/fixtures/` is empty. `FIXTURE_MODE=true` is how the demo runs with zero
credits (SRS P7) and how the tests avoid spending a budget — but a fixture is a
**recorded** response, not a plausible one. Hand-writing a temperature field would
launder invented measurements into the map, which is the same P1 violation as
inventing catalog costs. So the pipeline fails loudly with no fixtures rather than
degrading to synthetic data, and `fixture_strict` defaults to `true`.

Needs a `FORTYGUARD_API_KEY` and 14 calls per district — once. Every later run is free.
Full contract in `backend/data/fixtures/README.md`.

**Blocks:** the offline demo, and any integration test of the pipeline.
**Needs first:** the `geo` module for tiling (Task 3).

- [ ] `scripts/harvest_fixtures.py`
- [ ] Capture Phoenix
- [ ] Capture two more preset districts

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

### Task 4 · `backend/ml/` — model and attribution
- [ ] Feature assembly from `tile_features` + FortyGuard `tcm`
- [ ] LightGBM quantile models at p10 / p50 / p90
- [ ] Training script, held-out validation, metrics persisted
- [ ] TreeSHAP per-tile attribution → `attribution` table
- [ ] Out-of-support detection (reject rather than extrapolate)
- [ ] Model card: what it does and does not support

**Acceptance:** every prediction returns an interval, not a point. Out-of-support
inputs are rejected with a reason rather than silently extrapolated.

### Task 5 · `backend/optimizer/` — the exceedance ladder and plan search
**Depends on:** B-1 (catalog data), Task 3, Task 4.

- [ ] Exceedance ladder: 11 cached `exceedance` calls at T…T+10 °C
- [ ] Δhours = ladder(T) − ladder(T+ΔT), under the stated uniform-diurnal-shift assumption
- [ ] Person-heat-hours = population × hours-above-threshold
- [ ] Equity weighting `PHH × (1 + λ·SVI)`, λ surfaced as a policy choice not a constant
- [ ] Counterfactual feature transforms per intervention
- [ ] Clamp ΔT to the catalog's cited `[delta_c_low, delta_c_high]`
- [ ] Greedy marginal-benefit-per-dollar selection under the budget
- [ ] Feasibility rules per tile
- [ ] Label every counterfactual a planning-grade estimate under stated assumptions

**Acceptance:** a plan never exceeds budget, every ΔT is clamped to a cited range,
and no output claims an intervention *caused* a measured reduction.

### 🟡 Task 6 · `backend/agent/` — numeric guard DONE, graph remaining
- [x] `numeric_guard`: deterministic extraction + set-membership check
- [x] Retry-on-violation, then fail closed to the number-free template
- [x] Adversarial test battery (43 tests)
- [ ] LangGraph, 5 nodes only
- [ ] Persist node trace, guard verdict and violations to `agent_runs`
- [ ] Model: `claude-opus-5`

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

### Task 7 · `backend/report/` — the Cooling Action Plan PDF
- [ ] Report renderer with the provenance table
- [ ] Every figure traceable to an `fg_requests.activity_id` or a `plan_items` row
- [ ] Citation appendix reproduced verbatim from the catalog
- [ ] Measurement/verification protocol section
- [ ] Re-verify plan totals against items before export (`verify_totals`)
- [ ] Limitations page, stated plainly

**Acceptance:** no figure appears in the PDF without a provenance chain, and a
plan whose totals drifted cannot be exported.

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

### Task 9 · AOI Studio (SRS screen #2) · `/studio`
- [ ] Draggable/resizable AOI box on the map
- [ ] Live geodesic area badge against the plan cap
- [ ] Date / hour / granularity / threshold pickers
- [ ] Client-side pre-validation mirroring the backend guards (US coverage, ≤ cap, date floor)
- [ ] Credit-cost preview before submit

### Task 10 · Cooling Action Plan (SRS screen #8) · `/plans/[id]`
- [ ] Report preview
- [ ] Plan table with per-item intervals
- [ ] Download action
- [ ] Measurement plan section
- [ ] Provenance table

### Task 11 · Agent Trace + Methods (SRS screen #10) · `/trace/[id]`, `/methods`
- [ ] Node-by-node execution log
- [ ] Guard verdict and any violations, shown not hidden
- [ ] Model validation metrics
- [ ] Limitations page

### Task 12 · Impact & Equity (SRS screen #7, P1) · `/p/[id]/equity`
- [ ] Vulnerable-group breakdown
- [ ] Person-heat-hours by decile
- [ ] λ sensitivity view
- [ ] SVI tract-resolution caveat displayed, not buried

### Task 13 · Verify (SRS screen #9, P1) · `/plans/[id]/verify`
- [ ] Protocol display
- [ ] Re-measure trigger
- [ ] Predicted vs observed with the control comparison
- [ ] Explicit "within interval / outside interval" verdict, no causal language

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
