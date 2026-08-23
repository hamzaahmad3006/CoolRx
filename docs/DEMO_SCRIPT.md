# CoolRx — demo script

Required by the §24.8 pre-submission checklist. Two things live here: the **3-minute
video** that is a mandatory submission item, and the **demo-day protocol** (SRS §19.4)
for anything shown live.

**Hard constraint: 3 minutes maximum.** That is roughly 400 spoken words. Everything
below is timed. If a section overruns, cut from §4 (Verify), not from §1 or §2.

**Two rules from FortyGuard's own kickoff, worth obeying:**

- Judges prefer *you* narrating your own product over a polished AI-produced film.
  A plain screen recording with your voice scores better than something slicker.
- Show it **working**. Slides alone do not count.

---

## The 3-minute video

### 0:00–0:25 · The problem, in one concrete image

Do not open with the product. Open with the decision a city actually faces.

> "A city has $2 million for cooling and forty candidate blocks. Today that choice is
> made from a satellite land-surface map at 1 km resolution — which cannot tell you
> that this bus stop is 4 °C hotter than the one two streets over. CoolRx makes that
> choice measurable."

**On screen:** the AOI map, one district, tiles coloured by temperature.

### 0:25–1:10 · Diagnose — the measurement is real

Draw or load the Phoenix AOI. Run the diagnosis. While it runs, say what is happening:
four FortyGuard analytics — `tcm`, `exceedance`, `persistence`, `time_of_measure` — at
2 m above ground, 60–100 m tiles.

> "This is not modelled from weather-station data. It is FortyGuard's measurement at
> head height, on this block, at this hour."

**On screen:** analytic layers toggling; the hotspot ranking appearing.

**Say these numbers** — they are what central Phoenix actually returns, verified
2026-08-23. Do not round them up on camera:

| | |
|---|---|
| district mean | **37.07 °C** |
| range across the district | **36.80 – 37.13 °C** |
| blocks measured | **1,190** |
| top block by exposure | **49 person-heat-hours** |

The legend must read about 36.8–37.1. If it reads 0–1 the frontend is on an old
build and the map is meaningless.

### 1:10–1:55 · Prescribe — the part nobody else has

Set the budget, press **Optimize plan**, and let it run — it is a background job
and takes a few seconds. Do not cut this; watching it solve is the point.

> "Every intervention carries a predicted ΔT with a prediction interval, not a point
> estimate. The cost and the effect range come from published sources — the citation
> is in the report a planner reads."

**On screen:** budget → plan solves → before/after swipe on one locked colour domain.

**Say one interval out loud** so the honesty is audible. The real one at a
$400,000 budget:

> "Minus one point six degrees, with an interval of minus two point zero to minus
> one point two. That range is not the model's confidence — it is the published
> range from the EPA compendium and Brousse 2024, and the model is clamped to it."

| | |
|---|---|
| blocks selected | **60** |
| committed | **$393,840** of $400,000 |
| per block | **$6,564** for 400 m² of cool-roof membrane |
| predicted ΔT | **−1.6 °C (−2.0 to −1.2)** |
| dangerous hours avoided | **18** |
| people reached | **1,827** |
| person-heat-hours | **539** |

On the Before/After screen the shared scale reads **35.2 – 37.1 °C** and the
predicted-change histogram is **negative**. If it is positive, stop and fix it
before recording — that means the page is differencing a model prediction against
a measurement instead of applying the plan's cooling.

### 1:55–2:30 · The Cooling Action Plan

Generate the PDF. Scroll it on screen.

> "This is the deliverable — procurement-ready, and every figure traces to a FortyGuard
> `activity_id`. Here is the provenance table."

**On screen:** PDF with provenance rows and the attribution footer.

### 2:30–2:50 · Volunteer a limitation

Do this. It is the strongest 20 seconds in the video and almost nobody does it.

Open **Methods** and read the model card on camera. It is generated from the
model's own metrics file, so it cannot flatter the model.

> "This model does not transfer. On a city it was not trained on it explains
> essentially none of the variation — R squared of minus zero point zero zero
> nine. It is about as accurate as predicting the district average, and the page
> says so. The intervals hold ninety-three percent against a nominal eighty, so
> they are wider than calibrated — cautious, not overconfident, and labelled as
> neither. And two features have no citable source, which means an intervention
> acting only through them is predicted to do exactly nothing. Not a small
> effect. Nothing."

Then the verification caveat:

> "A later re-measure will include weather variation, not just the intervention.
> The control tiles are named in the protocol before any follow-up exists, so they
> cannot be chosen afterwards to flatter the result. That reduces the confound. It
> does not remove it."

### 2:50–3:00 · Close

> "US coverage today, because that is where the instrument reads. Built solo on
> the FortyGuard Temperature API — every number on screen traces to a measurement
> or a citation, and the ones that do not exist are labelled as missing rather
> than filled in."

---

## Pre-record checklist

- [ ] Run the whole flow once beforehand so every response is cached — no live latency on camera
- [ ] `FIXTURE_MODE=true` so the demo cannot fail on a network blip or spend credits
- [ ] Browser at 1920×1080, no bookmarks bar, no notifications, one tab
- [ ] **No API key visible anywhere** — not in a terminal, an env pane, a network tab, or a config file. Exposure is disqualification
- [ ] OSM + FortyGuard attribution visible on the map and in the PDF
- [ ] Say at least one prediction interval aloud
- [ ] Volunteer at least one limitation
- [ ] Under 3:00. Check the runtime before uploading
- [ ] Upload unlisted to YouTube or Loom; confirm it plays in a private window

## Demo-day protocol (SRS §19.4)

1. **Fixture mode is the default**, not the fallback. The recorded responses are committed, so the demo runs with no key and no network.
2. **Pre-warm** the three preset districts before presenting.
3. **Keep a local instance running** as a live backup if the deployed URL is being shown.
4. **If something breaks on camera, say so and continue.** A visible degraded banner with an honest sentence costs less than a pretence that unravels under a judge's question.

## What not to do

- Do not narrate the architecture. Judges score the problem and the result; the repo shows the build.
- Do not show code unless it is the one real API request/response the README requires.
- Do not claim CoolRx *causes* cooling. It predicts a response and pre-registers a measurement. The language rules in SRS §20.5 apply on camera exactly as they do in the UI.
