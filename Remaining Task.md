# CoolRx — Remaining Tasks

Working document. Tasks are ordered by dependency, so doing them top-to-bottom
avoids writing anything twice. Each is sized to be finishable and verifiable on
its own.

**Last updated:** 2026-08-12 · **Commits so far:** `b40b240`, `1b0e214` · **Tests:** 207 passing

---

## Status at a glance

| Layer | Done | Remaining |
|---|---|---|
| Frontend pages | 4 of 10 | 6 screens + 1 overlay |
| Backend persistence | ✅ complete | — |
| Backend pipeline | 0 of 5 modules | `geo`, `ml`, `optimizer`, `agent`, `report` |
| Backend API surface | health only | schemas, controllers, routes, workers |
| Data | — | ⚠️ intervention catalog (see blocker) |

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

### Task 2 · Controllers, routes and workers
- [ ] `controllers/projects.py` — AOI validation → geodesic area → persist
- [ ] `controllers/diagnose.py` — orchestrate the diagnose pipeline as an RQ job
- [ ] `controllers/prescribe.py` — orchestrate the plan pipeline as an RQ job
- [ ] `controllers/jobs.py` — status reads, SSE stream
- [ ] `controllers/catalog.py` — catalog reads for the UI
- [ ] `routes/` — one router per controller, `/api` prefix, no business logic
- [ ] `workers/` — RQ queue setup, job entry points, stale-job reaper
- [ ] `middleware/` — error envelope, rate limit, demo-key gate
- [ ] Wire fixture mode end-to-end so the frontend can integrate before the ML lands

**Acceptance:** frontend can drive a full diagnose→prescribe flow against fixtures
through real HTTP, with honest job progress.

---

## Phase B — The pipeline (bottom-up, each usable alone)

### Task 3 · `backend/geo/` — tiling and feature enrichment
- [ ] Tile grid generation from an AOI at 60/80/100 m
- [ ] Stable `tile_key` (geohash of centroid) so one ground location keeps one key
- [ ] NLCD land cover → canopy / impervious / building / water / grass-shrub %
- [ ] Albedo proxy, openness proxy (OSM footprint density — **not** a true sky-view factor, SRS NG-12)
- [ ] Elevation, local relief, distance to water
- [ ] Census dasymetric population + SVI join at tract resolution
- [ ] Mark every derived field's resolution so the UI can caveat it

**Acceptance:** an AOI produces a complete `tile_features` + `exposure` table with
nulls where data is genuinely missing — never zeros standing in for missing.

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

### Task 6 · `backend/agent/` — LangGraph and the numeric guard
- [ ] 5 nodes only, as specified — no more
- [ ] `numeric_guard`: deterministic regex + set-membership check that no
      LLM-generated numeral reaches output
- [ ] Retry-on-violation, then fail closed to the number-free template
- [ ] Persist node trace, guard verdict and violations to `agent_runs`
- [ ] Model: `claude-opus-5`

**Acceptance:** the guard is tested against adversarial cases — an LLM that
invents a figure must be caught, and the plan must remain valid with the prose
dropped entirely.

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

### Task 8 · Attribution drawer (SRS screen #4) · overlay on Diagnosis
- [ ] SHAP waterfall chart
- [ ] Land-cover donut
- [ ] Exposure summary for the selected tile
- [ ] Provenance link for the tile's source analytic run

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
