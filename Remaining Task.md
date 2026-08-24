# CoolRx — Remaining Tasks

Working document. Tasks are ordered by dependency, so doing them top-to-bottom
avoids writing anything twice.

**Last updated:** 2026-08-24 · **Target:** core complete 24 Aug, submit by 29 Aug ·
**Tests:** 742 passing, 0 skipped with Postgres and Redis up

> Everything below the "Status at a glance" table is the older working log, kept
> for its reasoning. Where it disagrees with this header, this header is right.

---

## 24 August — portability pass

The suite had only ever been run on this machine's Python 3.14. Running it on
**3.12 — the version in `backend/Dockerfile` and in CI** — surfaced three defects
that 3.14 hides, and a fourth that nothing hid.

### P0 · Every domain error was a 500 on 3.12 and 3.13

`CoolRxError` is `@dataclass(slots=True)` and its `__post_init__` called
zero-argument `super().__init__`. A slots dataclass is a *replacement* class, and
below CPython 3.14 the `__class__` cell captured by that `super()` still points at
the discarded original, so the call raises

```
TypeError: super(type, obj): obj must be an instance or subtype of type
```

**at construction**. Every `NotFoundError`, `AoiRejectedError`,
`JobAlreadyRunningError` and `ValidationFailedError` therefore escaped as an
unhandled 500 instead of its mapped status — a rejected AOI would have told a
judge "something went wrong" instead of "63.20 mi² is above the 10.00 mi² limit".

It has never shown up locally because 3.14 started rewriting that cell. It would
have shown up on the deployed demo, which is `python:3.12-slim`.

- [x] `Exception.__init__(self, self.message)` explicitly, with the reason recorded
      at the call site
- [x] Verified on 3.12: `tests/test_error_envelope.py` 18/18, was 14/18

### P1 · The per-run statistics block was null for every temperature run

`stats_data` is not one shape. `tcm` nests its figures under
`stats_data.temperature_stats` as `minimum` / `maximum` / `standard_deviation`;
exceedance, persistence and time-of-measure send a flat `min` / `max` / `mean`
with `n_cells` and `units`. `analytic_run_to_response` validated the stored blob
straight into the flat `FgStats`, so it read the second shape and returned an
all-null block for the first — and raised nothing, because every field on
`FgStats` is optional by design.

The effect was quiet in exactly the way that survives review: the exceedance runs
listed beside it looked correct, and the project summary was right too, because
`AnalyticsController._stats_of` had already been fixed to read the nested block.
Only the `tcm` row — the run the whole diagnosis is about — was empty.

- [x] `controllers.adapters.stats_of_run` reads both shapes: `read_stat` first,
      then the flat short keys, then `n_cells` as the count
- [x] 3 regression tests, one per shape plus the empty case
- [x] Verified against a live run: `tcm` now reports min 36.8048 / max 37.1297 /
      mean 37.0735 / std 0.0601, matching the summary block exactly

### P1 · CI could not have been green

Three separate reasons, all in the backend job:

  1. `tests/test_plan_report.py` imports `pypdf`, which was in no dependency
     group — 3 collection errors that read as report regressions.
  2. No `alembic upgrade head`, so the Postgres-backed tests ran against an empty
     database and the readiness checks failed on a missing table.
  3. No catalog load, so AC-23's "the boot gate refuses an empty catalog" test
     asserted against an empty catalog.

- [x] `pypdf` added to the `dev` extra
- [x] `Migrate` and `Load intervention catalog` steps added before `Tests`
- [x] `ruff check .` — 207 findings at HEAD, now **clean**. 97 auto-fixed, 27 files
      run through `ruff format`, the rest fixed by hand. Five rule families are
      ignored in `pyproject.toml` with the reason written next to each; the one
      worth naming is **RUF001 in `agent/numeric_guard.py`**, where the U+2212
      MINUS SIGN is load-bearing — the guard has to recognise the typographic
      minus a model emits, so "correcting" it to a hyphen would open the bypass
      the module exists to close.
- [x] Two real defects fell out of the lint pass: `Any` was used in
      `repositories/catalog.py` without being imported (harmless under
      `from __future__ import annotations`, a `NameError` the moment anything
      calls `get_type_hints`), and `routes/system.py` shadowed the `credits`
      builtin.

### P1 · FR-006 and FR-007 were never fetched

`optimizer/priorities.py` looks up the latest `persistence` and `time_of_measure`
run and converts the peak hour to district-local; `PriorityRow` carries
`persistence_hours` and `peak_hour_local`; the frontend ships a peak-hour clock;
and `controllers/projects.py` quotes a diagnosis at *one tcm, one time_of_measure,
one persistence and eleven exceedance steps*. The pipeline was the only link that
never made the two calls — so the credit estimate charged for them, both columns
were null for every tile, and the clock had nothing to draw.

- [x] `_fetch_secondary_analytics` in `workers/pipeline.py`, after the ladder.
      Each call is caught separately: a failure costs two columns and is named in
      the degradation reason, rather than failing a diagnosis whose temperature
      field and ladder are already persisted
- [x] Verified on a live run: `persistenceHours` 1.0 and `peakHourLocal` 22 now
      populate, and the run stores `tcm`, `time_of_measure`, `persistence` and
      11 × `exceedance`
- [x] Zero credits in fixture mode — both were harvested for all three districts
      back in August and were sitting unused

**Both columns are constant across a district, and that is arithmetic.** A
diagnosis requests a single hour, so hours-above-threshold can only be 0 or 1
(Phoenix reads 1.0 at ~37 °C, Las Vegas 0.0 at ~34.6 °C) and a peak hour chosen
from a one-hour window has one candidate. They carry spatial information only
over a multi-hour window. Recorded in the module docstring so a reviewer does not
read a constant column as a bug — and so whoever widens the window knows where to
look. Also noted there: FR-007 specifies converting the peak hour with
`env_params.metadata.timezone_offset_hours`, and the code converts from longitude
because `env_params` (FR-008) is not wired. They agree for all three preset
districts, which are MST with no daylight saving. They will not agree everywhere.

### Verified rather than assumed

- **Parser against all 45 recordings** — 84,242 tiles, every one carrying a value,
  zero parse failures. `tcm` reads 30.18–37.28 °C across the six AOIs; Phoenix
  district 36.80–37.13, which is the legend `docs/LOCAL-TESTING.md` predicts.
- **Full journey, live services** — seed → diagnose (70 s, `degraded`, 1,190 tiles)
  → priorities → plan (76 items, $498,864 of a $500,000 budget, ΔT −1.6 °C
  [−2.0, −1.2] from the cool-roof row) → **4-page PDF** with the attribution on
  every page.
- **Model retrains reproducibly offline** from the committed feature cache and
  reproduces the shipped artefacts byte for byte — same MAE 0.273, R² −0.009,
  coverage 0.930, width 0.601 °C.
- **AC-15** — production bundle built and grepped: no FortyGuard, Anthropic or
  Groq key present.
- **`tsc --noEmit`** clean; `next build` compiles all 11 routes.

### Found, not fixed — decisions for you

- **No LLM key is configured.** `ANTHROPIC_API_KEY` and `GROQ_API_KEY` are both
  empty, so every plan finishes `degraded` with "plan text was not generated" and
  `/api/agent/plans/{id}/trace` returns 404. The figures are unaffected — that is
  the design — but the Agent Trace screen has nothing to show, and it is one of
  the ten screens. Groq's free tier needs no card.
- **The demo needs the internet, not just credits.** `FIXTURE_MODE=true` removes
  the FortyGuard calls, but the enrichment stage still fetches NLCD, 3DEP, ACS and
  Overpass live, so a diagnosis run without network resolves no features, no
  population, and no attribution. `data/features/*.json` already holds real
  provider output for all six AOIs; letting the pipeline fall back to it would
  make `make demo` genuinely offline. Not done here: it changes the most important
  pipeline stage, and how a cached-feature run is labelled is a provenance
  decision, not a refactor.
- **`next/font/google` fetches at build time**, so any build host without access
  to `fonts.googleapis.com` fails the production build outright. Fine on Railway;
  worth knowing before it surprises you.
- **mypy reports 506 errors under `strict` + `disallow_any_explicit`.** CI has it
  `continue-on-error`, so nothing is blocked. Pre-existing, untouched.
- **ESLint: 7 errors, 48 warnings.** CI does not run it. Untouched.

---

## What is left — 23 August

Three items are **mandatory for the submission** and none of them can be done
without you.

| # | Item | Blocked on |
|---|---|---|
| 1 | **Live demo URL** | your Railway account — guide at `infra/railway.md` |
| 2 | **Video, ≤3 min** | recording — script at `docs/DEMO_SCRIPT.md`, numbers verified |
| 3 | **Submission form** | your submission — text ready at `docs/SUBMISSION.md` |
| 4 | Add `hackathon@fortyguard.com` as collaborator | your GitHub |

One open technical item:

| # | Item | State |
|---|---|---|
| 5 | Verify the trimmed API image imports cleanly | Docker daemon wedged mid-session; image store emptied on restart. Needs a rebuild and one `import rasterio` check. |

### Known limitations, decided rather than outstanding

These are **not** todo items. Each was investigated and closed with a reason;
they are listed so nobody reopens them by accident.

* **`albedo_proxy` and `openness_proxy` are null.** No citable source. Albedo
  needs a per-class reflectance table, openness needs building heights. The
  consequence — a `material` intervention is predicted to do exactly nothing —
  is published in the model card rather than hidden.
* **`shade` and `water` are not in the catalog.** A tile is 100 m × 100 m; a bus
  shelter shades about 10 m². It changes radiant temperature for a person under
  it, not air temperature over a hectare. Reasoning in
  `backend/data/CATALOG-RESEARCH.md`.
* **The model does not transfer across cities** (R² −0.009 held out). Stated on
  the Methods page and in the PDF.
* **Intervals are conservative, not calibrated** (93% against a nominal 80%).
  With two training districts each conformal fold fits on one city, so the width
  is cautious. More districts would tighten it; relaxing the check would not.
* **`units` is null for `tcm`.** The live API sends none. Labelling it would be
  inventing the unit (N-3).
* **SVI has no source.** The CDC dataset is published as a map asset with no
  queryable columns, so the equity quartile reports null.

---

## Status at a glance

| Layer | Done | Remaining |
|---|---|---|
| Frontend pages | ✅ 10 of 10 + drawer | — |
| Deployment | ✅ Makefile · both Dockerfiles · CI · compose web · demo script | ⚠️ no live URL yet |
| Backend persistence | ✅ complete | — |
| Backend pipeline | ✅ all modules built | raster/census providers; training on real data |
| Backend API surface | ✅ 20 routes wired | worker stages that call the pipeline |
| Local env | ✅ `.venv` + all deps install | — |
| FortyGuard API | ✅ live, authenticated, parsed | — |
| Data | ✅ fixtures, 3 districts, provenance, 15.4 MB | ⚠️ catalog 1 of 4 rows |

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

### ✅ N-7 · Trainer entry point, frontend in compose, data licences — DONE 2026-08-18

**`backend/scripts/train_model.py`** — the `make train` target referenced a script
that did not exist. It does now, and it refuses to train when training would be
dishonest. Two preconditions, checked before any booster is fit:

  1. *Grouped holdout needs 2+ districts.* `TrainingReport` splits by district
     because tiles within one are spatially autocorrelated; a random split leaks
     neighbours and reports accuracy the model does not have. Only Phoenix is
     harvested.
  2. *The feature vector needs the raster/census providers.* `FEATURE_ORDER` is 13
     features; 3 resolve today (`hour_utc`, `doy`, `latitude`). A model fit on
     those still yields TreeSHAP attributions — attributing urban heat to latitude
     and time of day, which is not what FR-011 promises a planner.

`--check` reports readiness as JSON. Verified against the committed fixtures: it
finds **1,190 labelled tiles**, correctly ignores the exceedance/persistence
recordings (hour counts, not temperatures), and blocks with both reasons named.
`--allow-thin-features` exists for experimentation and marks output `honest: false`.

- [x] `scripts/train_model.py` with readiness gating
- [x] `--check` verified against real fixtures
- [ ] Feature-row assembly past the gate — deliberately unwritten until the
      providers exist; fabricating rows is the violation the script prevents

**Frontend in `infra/docker-compose.yml`** — a `web` service was missing, so
`make demo` could bring up the API but not the UI.

- [x] `web` service, `api` profile, healthcheck, public-only build args
- [ ] Verify `docker compose --profile api up` end to end (Docker not run here)

**`docs/DATA_LICENSES.md`** — required for submission by SRS §12.2.1 (AC-21).
Every dataset with licence and rendered attribution. States CoolRx's ODbL
share-alike position explicitly: results and a fixed fixture sample are
distributed, not an OSM-derived database, so share-alike is not triggered — and
says what would change that.

- [x] `docs/DATA_LICENSES.md` written
- [ ] Attribution actually rendered on map views and in the PDF (compliance
      checklist inside the file is unticked — it documents the obligation, it does
      not satisfy it)

---

### ✅ N-8 · Fixture provenance — FIXED 2026-08-19 · Census still needs a key

**Las Vegas captured.** 28 recorded responses now committed, 14 per district.
`train_model --check` reads **2,353 labelled tiles** across both, up from 1,190.

- [x] Capture Phoenix
- [x] Capture Las Vegas
- [ ] Capture Tucson — the third preset, 14 more calls

**But the holdout gate still cannot pass, for a reason I got wrong.** The trainer
blocks on "only one district", and that is not what is happening. The fixture
envelope stores only `{map_data, stats_data}` — **no request body, no district, no
activity_id**. So both districts read back as `"unknown"` and `district_count` is 1
no matter how many are harvested.

This is a defect in the fixture *format*, not the harvest, and it reaches further
than training:

  * `train_model` can never satisfy its own grouped-holdout precondition
  * FR-019 promises every FortyGuard-derived figure resolves to an `activity_id`
    in `fg_requests`; a fixture-backed run has no activity_id to resolve to
  * a reviewer cannot tell what request produced a given recording, which is the
    thing `data/fixtures/README.md` says the envelope is for

**Fix:** have `FixtureStore.save` write `{request, response, district, activity_id,
captured_at}` and have `load` keep tolerating the bare-result shape so the 28
already captured stay readable. Then re-harvest, or backfill the metadata.

- [x] **Root cause was narrower than described.** `FixtureStore.save` already wrote
      a rich envelope; `harvest_fixtures.py` never called it, writing `result.result`
      straight to disk instead. Fixed at the write path rather than the format.
- [x] `FixtureStore.save` takes optional `meta`; harvest now records district,
      district_name, analytic_type, threshold_c, activity_id and captured_at
- [x] **All 28 existing fixtures backfilled without spending a credit.** The
      filename *is* `compute_request_hash(endpoint, payload)`, so replaying each
      district's plan reconstructs the hash → district mapping exactly.
      `scripts/backfill_fixture_provenance.py`, 28 upgraded, **0 unmatched**.
      `activity_id` is set null, not invented — it was never recorded — and the
      recordings are stamped `provenance_backfilled: true` so a reviewer can tell
      which have a real task id behind them.
- [x] `train_model --check` now reports **2 districts** (phoenix, lasvegas),
      2,353 labelled tiles, **`grouped_holdout_possible: true`**
- [x] Two regressions from this change caught and fixed: the trainer stopped
      reading the new envelope shape, and re-serialising with indent pushed the
      fixture set to 28.6 MB, over the 25 MB budget in SRS §12.4. Now compact:
      **10.2 MB**
- [x] All 28 fixtures still parse; suite still 522 passed / 38 skipped / 0 failed

**Training precondition 1 is now satisfied.** The trainer blocks on one thing only:
10 of 13 features need the NLCD, terrain and census providers.

**The US Census API now requires a key.** SRS §12.2 lists ACS as open. As of
2026-08-18 an unauthenticated request returns a "Missing Key" HTML page, so
population, age and poverty features cannot be built without one. Free and instant
from <https://api.census.gov/data/key_signup.html>.

- [x] `CENSUS_API_KEY` added to `.env.example` and `core/config.py`, optional so a
      missing key leaves those features null rather than refusing to start
- [ ] **Needs you:** register for a key
- [ ] Then write the census provider

**README** brought back in line with reality: 20 endpoints not 18, 559 tests not
530, fixtures present rather than "empty", `make demo` documented, and the two new
prerequisites recorded.

- [x] README status corrected

---

### ✅ N-9 · Tucson captured · attribution rendered — DONE 2026-08-19

**Third district harvested.** 42 recorded responses now committed across
phoenix, lasvegas and tucson. `train_model --check` reads **3 districts** and
**3,543 labelled tiles**.

- [x] Capture Tucson

**Fixture writer was still pretty-printing.** The new provenance envelope went
through `FixtureStore.save`, which used `indent=2`, so the Tucson batch landed
verbose and the set hit 24.7 MB — one rounding error from the 25 MB ceiling in
SRS §12.4. The writer now emits compact JSON and the whole set was re-serialised:
**15.4 MB**.

- [x] `FixtureStore.save` writes compact JSON
- [x] Set re-serialised, back inside budget

**AC-21 attribution — the half that was missing.** The frontend already carried
`BRAND.attribution` into all three map components. The PDF carried nothing, and
SRS §12.2.1 names the PDF explicitly. `report/pdf.py` now stamps
"© OpenStreetMap contributors · Temperature data © FortyGuard" on every page
footer, so it survives someone printing or sharing a single sheet.

Verified against rendered bytes, not by reading the source: reportlab writes page
streams through ASCII85 *then* Flate, and splitting on `b"stream"` also matches
inside `b"endstream"` — both traps silently pass a document with no attribution.
The test undoes both layers properly.

- [x] Attribution on every PDF page
- [x] `test_every_page_carries_the_required_attribution` asserts it in the output
- [x] Frontend attribution confirmed already present (all three map components)
- [ ] Tick the compliance checklist in `docs/DATA_LICENSES.md` once a reviewer
      has seen both surfaces

---

### ✅ N-10 · Premium unlocked · SRS aligned · demo script — DONE 2026-08-19

**C-8 / Q-04 are closed.** Official #announcements, 18 Aug: the hackathon key is
**fully Premium — every endpoint unlocked, free, 2,000,000 credits, valid 5 weeks.**
The SRS had been carrying this as unknown and defaulting to Basic since 8 Aug.

- [x] `FG_PLAN=premium` in `.env` and `.env.example`
- [x] AOI cap **10 → 50 mi²** — `config.py:201` already auto-raised it on the plan
      switch, so this needed no new code
- [x] `FG_ENABLE_SATELLITE` / `_STREETVIEW` / `_HEAT_INTELLIGENCE` all on
- [x] FR-027 / FR-028 / FR-029 retagged from PREMIUM-DEPENDENT to **AVAILABLE**
- [x] The `PREMIUM-DEPENDENT` tag definition itself now records the resolution, so the
      11 scattered uses read correctly without 11 risky edits
- [x] Q-04 struck from the Day-1 blocking questions — answered from an announcement
      rather than by spending a probe call

**Two things deliberately *not* changed:**

`FG_CREDIT_RESERVE` stays at 50,000. Against 2,000,000 that is a 2.5% floor — sane, and
lowering a safety margin for no reason is not an improvement.

**G-12 ("core works on API Basic only") stays a goal.** Premium being available is not a
reason to put it on the P0 path. The flags cost nothing and are what make a 403, credit
exhaustion, or a post-hackathon downgrade a non-event instead of a broken demo.

**`docs/DEMO_SCRIPT.md` written** — required by the §24.8 checklist and previously absent.
A timed 3-minute cut (the video is a mandatory submission item), a pre-record checklist
with the no-visible-key rule, and the §19.4 demo-day protocol. Follows FortyGuard's own
kickoff guidance: the builder narrating beats a polished AI-produced film, and slides
alone do not count.

- [x] `docs/DEMO_SCRIPT.md`
- [ ] Record the video against the deployed demo once one exists

---

### 🟡 N-11 · NLCD providers — impervious + canopy LIVE, class layer deferred

**Two of the ten missing features now resolve from real data.** `geo/mrlc.py`, verified
live against the Phoenix AOI on 2026-08-19:

| Tile | impervious_pct | canopy_pct |
|---|---|---|
| a | 82.52 | 0.62 |
| b | 91.25 | 0.00 |
| c | 87.62 | 0.06 |
| d | 78.54 | 0.38 |

100% coverage, no API key, MRLC WMS. Dense pavement and almost no canopy — which is
what downtown Phoenix is.

**Design: one raster per AOI, not one query per tile.** The obvious approach is a
`GetFeatureInfo` per tile, but a district is ~1,200 tiles × 2 layers ≈ 2,400 requests
against a free public service *per diagnosis*. Instead each layer is fetched once as a
GeoTIFF sized to NLCD's native 30 m grid and sampled locally. Two requests per district;
the Phoenix raster is ~2.5 KB. Tiles take the **mean** of the cells they cover, not the
centroid value — a 60–100 m tile spans several 30 m cells.

- [x] `ImperviousProvider` → `impervious_pct`
- [x] `TreeCanopyProvider` → `canopy_pct`
- [x] 9 tests, all offline (stubbed transport; the suite must never call mrlc.gov)
- [x] No-data (250–255) dropped before averaging, never clamped into a percentage
- [x] Transport failure yields misses, not an exception — the `fetch` contract

**Deferred, deliberately: `water_pct`, `grass_shrub_pct`, `albedo_proxy`.**
These need the land-cover *class* layer, and over WMS `NLCD_2021_Land_Cover_L48`
returns **rendered palette indices, not class codes** — the Phoenix raster came back
holding {4, 5, 6} where NLCD classes are 11/21/…/95. `GetFeatureInfo` on the same pixel
reports 24 (Developed, High Intensity), so index ≠ class and the mapping is
undocumented. Inventing it would put fabricated land-cover under every downstream
figure — the same P1 violation as inventing a catalog cost.

- [ ] Read true class values — WCS is the likely route (`mrlc_display__NLCD_2021_Land_Cover_L48`
      exists) but axis subsetting rejected both the geographic and the Albers envelope;
      needs its own investigation
- [ ] Then `water_pct`, `grass_shrub_pct`, `albedo_proxy`

**Still open on the feature vector:** 8 of 13 unresolved. Elevation and relief are next
and unblocked — the 3DEP point service was probed and returned 331.38 m at 1 m
resolution for the Phoenix centroid, no key.

---

### 🟡 N-12 · Census exposure provider — population + age LIVE

**`geo/census.py`.** Verified live on the Phoenix AOI, 2026-08-19: three block groups
intersect it (1,929 / 2,026 / 2,654 people), four test tiles received 61.5–144.8 people
each at 3.6–7.0% aged 65+. 100% coverage.

This is the half of the impact story that was inert. `person_heat_hours` returned
`None` for every tile because population was unknown; it can now be computed.

- [x] `population` and `pct_over65` at true block-group resolution
- [x] Boundaries from **TIGERweb** (no key) + attributes from **ACS 5-year** (key)
- [x] Areal apportionment, **conserves the block-group total** — which is what AC-04 checks
- [x] `pct_over65` is population-weighted, so a tile straddling two block groups gets
      the mix its people actually come from rather than a flat average
- [x] 12 tests, all offline — both upstreams stubbed

**`pct_poverty` deliberately not populated.** ACS publishes `B17001_002E` at **tract**
level, not block group — verified, the block-group query returns `null` for every row.
Serving a tract figure from a provider that declares block-group resolution would
overstate its precision, the same way the SRS insists SVI be labelled at its true tract
resolution. It needs its own provider with its own declared resolution.

- [x] **`pct_poverty` — DONE 2026-08-20**, `geo/poverty.py`. Live on the Phoenix AOI:
      18.4% – 37.6% across four tiles, and tract 1131's own figure (1,885 of 5,011 =
      37.6%) lands exactly on the tile sitting wholly inside it.
- [x] Separate provider precisely so the resolution can be declared honestly — ACS
      publishes B17001 at **tract** level only, verified: the block-group query
      returns `null` for every row.
- [x] **A rate is assigned, not apportioned.** 37.6% over a tract does not become
      11% because a tile covers 30% of it. Straddling tiles get an area-weighted
      *mix* of the two rates, never a dilution of either. This is the bug that would
      have quietly deflated every equity figure.
- [x] Boundaries reuse the census TIGERweb query — a tract GEOID is a block-group
      GEOID's first 11 characters, so no extra endpoint to depend on
- [x] Universe of zero yields no rate, not 0% — nobody there had poverty status
      determined
- [x] 11 tests, all offline
- [ ] **SVI — still unsourced.** CDC/ATSDR publishes it at tract level, which would
      fit this provider exactly, but the data.cdc.gov dataset (`ypqf-r5qs`) is
      registered as a **map asset with zero queryable columns** — the Socrata row
      endpoint returns `[{}]` — and the other catalogue ids 404. Guessing a download
      URL risks loading the wrong vintage or geography under an equity weighting a
      city would act on, so `svi_score` stays null until the source is confirmed.

**Exposure: 3 of 4 fields now resolve** (`population`, `pct_over65`, `pct_poverty`).
The equity λ dial still multiplies against a null SVI and so does nothing yet.

**The apportionment assumption, stated plainly:** people are spread evenly within a
block group. They are not. A true dasymetric method weights by where buildings are, and
`impervious_pct` from `geo/mrlc.py` is now available as exactly that weight. This is the
largest single source of error in the exposure figures and is disclosed in the module,
the schema and the Methods page rather than buried.

- [x] **Weight apportionment by `impervious_pct` — DONE 2026-08-20.** People now
      follow built surface rather than being spread evenly. Live comparison on the
      Phoenix tiles: `a −1.0%`, `b +26.4%`, `c +1.6%`, `d +14.9%`; AOI total 390 → 429,
      because these downtown tiles are denser than their block groups' averages —
      which is the correction the method exists to make.
- [x] Weights normalised over the **whole** block group, not the AOI. Measured: the
      Phoenix groups are 2.2× wider and 2.5× taller than the study area, so
      normalising over AOI tiles alone would have handed the AOI ~100% of every
      group's residents.
- [x] Falls back to areal **per block group**, so one park with no built surface does
      not push the whole AOI onto the cruder method
- [x] A weight-surface outage costs accuracy, not the exposure layer
- [x] `ProviderInfo.source` names which method produced the numbers, since the
      Methods page reproduces it verbatim
- [x] 5 more tests (17 total on this provider), all offline

**Feature/exposure status: 5 of 13 model features + 2 of 4 exposure fields resolve.**

### ⛔ N-13 · Elevation blocked upstream — USGS 3DEP degraded

Not a code problem. Diagnosed 2026-08-19:

| Endpoint | Result |
|---|---|
| 3DEP service metadata | ✅ HTTP 200, 11 KB — service is up |
| `exportImage` (raster) | ❌ **504** at 80×60, 40×30 and 20×15 |
| EPQS point query | ❌ **504**, `{"message": "Endpoint request timed out"}` after 30 s |
| EPQS × 5 points | ❌ 2 of 5 returned, **139 seconds** |

The same EPQS call returned 331.38 m in under a second earlier the same day, so this
is a live degradation, not our request shape. No provider was shipped: at 28 s/point a
district would take 9+ hours, and committing something unverified against a source
returning 504s would put it in the demo path untested.

- [ ] Retry USGS — likely transient
- [ ] Or evaluate AWS Terrain Tiles (free, no key, raster) — **check its licence first**

---

### 🟡 N-14 · Land-cover classes solved — water + grass/shrub LIVE

**The WMS palette-index problem is resolved.** `geo/landcover.py` reads true NLCD
class codes over **WCS**. Two details, both found the hard way:

1. The coverage is published in **EPSG:3857**, not Albers 5070 — subsetting with
   Albers coordinates returns *"Empty intersection after subsetting"*, which is what
   made this look unreachable earlier.
2. GeoServer cannot write GeoTIFF in 3857 — *"Unable to map projection Popular
   Visualisation Pseudo Mercator"*. `outputCrs=EPSG:4326` reprojects and succeeds.

Subset in Web Mercator, request WGS84 out. The Phoenix box then returns
`{22: 4, 23: 181, 24: 595}` — Developed Low/Medium/High Intensity, real class codes.

**Discriminating check, live:** downtown Phoenix reads **0% grass/shrub** across four
tiles, a Papago Park tile reads **87.37%**. That contrast is the proof the class layer
is being read rather than render indices.

- [x] `water_pct` — class 11 only; 12 (perennial ice) excluded, it is not water that
      cools a street
- [x] `grass_shrub_pct` — classes 52 and 71; 81 pasture and 82 crops excluded, they
      are agricultural cover and the feature names grass and shrub
- [x] Fill values leave the **denominator** — counting them as "not water" would
      deflate every fraction
- [x] 13 tests, all offline

**`albedo_proxy` still null, deliberately.** The class layer could supply it, but it
needs a per-class reflectance table, and albedo feeds a predicted temperature
reduction a city would spend money on. An uncited constant there is the same P1
violation as an invented catalog cost.

- [ ] `albedo_proxy` — needs a citable per-class albedo table

**Model features: 7 of 13 resolve** — `hour_utc`, `doy`, `latitude`,
`impervious_pct`, `canopy_pct`, `water_pct`, `grass_shrub_pct`.
Remaining 6: `albedo_proxy`, `openness_proxy`, `building_pct`, `elevation_m`,
`local_relief_m`, `dist_to_water_m`.

---

### 🟡 N-15 · Terrain, water distance and buildings — 3 of 4 features LIVE

Both blocked upstreams recovered on 2026-08-21 and were re-probed before any code
was written: 3DEP answered, Overpass answered a light query.

**`geo/terrain.py` — `elevation_m`, `local_relief_m`. Verified live.**
Phoenix AOI: elevation 331.33–331.59 m, within-tile relief 0.82–4.33 m — a flat
desert city on a river plain, with some tiles measurably less flat than others.

The point service (EPQS) works but answers one coordinate per request, and on
2026-08-20 was taking ~28 s per point with 2 of 5 failing — nine hours for one
district. `exportImage` returns the whole AOI as one float32 GeoTIFF instead: one
request, ~66 KB. `pixelType=F32` matters; the default 8-bit render would quantise
away exactly the small relief this feature measures.

- [x] One raster per AOI, not one point per tile
- [x] Void sentinels (−3.4e38) excluded **before** the mean, not after
- [x] `local_relief_m` documented as *within-tile* spread, not a neighbourhood
      window — a window width would be an arbitrary parameter nobody could justify

**`geo/water.py` — `dist_to_water_m`. Verified live.**
Phoenix: 2.82–3.00 km to the nearest open water, decreasing steadily north-east.

- [x] Land cover fetched over the AOI **expanded by 10 km** — water that cools a
      district is frequently outside it
- [x] Distance transform in true metres, using metres-per-pixel at the window's own
      latitude (a degree of longitude is ~93 km at Phoenix, not 111 km — the
      equatorial figure would overstate every east–west distance by ~20%)
- [x] **No water in the window → null, never a floor value.** A tile 10 km from water
      and one 60 km from it both need a figure this method cannot produce

**`geo/buildings.py` — `building_pct`. Code complete, NOT live-verified.**

Overpass returned **504** from the main instance and **502** from the Kumi mirror for
the `out geom;` query this needs, minutes after answering a light `out count;`. So
unlike every other provider here, **no real Overpass payload has been parsed yet** —
recorded in the module docstring rather than glossed.

One thing was learned live and is now baked in: **Overpass answers 406 Not Acceptable
to the default `python-httpx` user agent**, before it parses the query at all, so the
failure reads as a malformed request rather than a blocked client. Their usage policy
also asks callers to identify themselves.

- [x] Single query per AOI — a per-tile query would be ~1,200 requests against a
      donated service per diagnosis
- [x] User-Agent set and asserted in tests
- [x] Overlapping footprints capped at 100% — OSM footprints do overlap
- [x] An AOI with nothing mapped → null, not 0%: far more likely unsurveyed than empty
- [ ] **Verify against a live Overpass response before these numbers are shown**

- [x] 27 tests across the three, all offline. Suite: **600 passed, 38 skipped, 0 failed**

**Model features: 11 of 13 resolve.** Remaining: `albedo_proxy` (needs a citable
per-class reflectance table) and `openness_proxy` (needs building heights).

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
