# FortyGuard response fixtures

**This directory is intentionally empty. Fixtures must be captured, not written.**

## Why

`FIXTURE_MODE=true` lets the whole demo run with zero API credits (SRS P7), which is
how the app is demonstrated and how the test suite avoids spending a budget. But a
fixture is a **recorded real response**, not a plausible one.

Hand-writing a temperature field would put invented measurements on the map. That is
the same violation as inventing intervention costs — principle P1 says every number
in every output originates from the API, the database, the model, or deterministic
Python. A fabricated fixture launders an invented number into all four.

So the pipeline fails loudly with no fixtures rather than degrading to synthetic data.
`fixture_strict` defaults to `true` for the same reason: a fixture miss raises instead
of silently falling through to a live call.

## Capturing them

Requires a `FORTYGUARD_API_KEY` and spends credits — once. Every later run is free.

```bash
FIXTURE_MODE=false python -m scripts.harvest_fixtures --city phoenix
```

The `harvest` job kind exists for exactly this (`JobKind` in `schemas/jobs.py`). One
harvest per preset district captures:

| Analytic | Calls | Purpose |
|---|---|---|
| `tcm` | 1 | The temperature field itself |
| `time_of_measure` | 1 | Peak hour per tile |
| `persistence` | 1 | Longest continuous run above threshold |
| `exceedance` | 11 | The ladder, at T … T+10 °C |

14 calls per district. Three preset districts is 42 calls.

## Naming

One file per request, named by the same `request_hash` the cache uses, so a fixture
lookup and a cache lookup resolve identically and fixture mode exercises the real code
path rather than a parallel one:

```
data/fixtures/<request_hash>.json
```

The hash is computed by the client from the endpoint and the request body, so the
harvest script writes them under the correct name automatically. Do not rename them.

## What lives in git

Fixtures **are** committed. They are part of the deliverable: a judge cloning the repo
must be able to run the full demo without an API key (SRS P7). They contain no
credentials — the API key travels in a header and never appears in a request body, and
`FgCacheRepository` strips secret-shaped keys defensively before persisting anything.

## Status

- [ ] Phoenix district captured
- [ ] Second preset district captured
- [ ] Third preset district captured
- [ ] `scripts/harvest_fixtures.py` written (needs the `geo` module for tiling — Task 3)
