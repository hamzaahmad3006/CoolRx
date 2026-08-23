# CoolRx — submission packet

Four items are required (FAQ canvas, confirmed 2026-08-18):

1. Live demo link
2. Video, max 3 minutes
3. Code on GitHub, with `hackathon@fortyguard.com` added as collaborator
4. Brief description, max 500 words

Deadline: **30 August 2026, 11:59 PM GST**. Form: <https://forms.gle/jLgBzVTG1NhJ3gNe6>

---

## Item 4 — description (436 words)

> **The problem**
>
> A heat map tells a city where it is hot. It does not tell them what to build,
> what it costs, or how many hours of dangerous heat it removes. Phoenix has had
> block-level temperature data for years; what it lacks is the step from a red
> square on a map to a line in a capital budget.
>
> **Who it is for**
>
> A city heat officer or public-works planner with a fixed budget who has to
> defend a spending decision. They need a number they can put in a procurement
> document and a source they can cite when someone challenges it.
>
> **What CoolRx does**
>
> It reads FortyGuard's street-level temperature field, finds the hottest blocks,
> explains what about their surface makes them hot, prescribes what to build
> under a budget, and produces a costed Cooling Action Plan with a pre-registered
> protocol to verify the result later.
>
> The step that makes it useful is the **exceedance ladder**. FortyGuard's
> `exceedance` analytic is queried at eleven thresholds, T through T+10 °C,
> producing a measured curve of hours-above-threshold per block. A predicted
> cooling of ΔT is then read off that same curve at T+|ΔT|. A temperature change
> becomes an *exposure* change — hours of dangerous heat avoided — using the
> API's own measurements rather than a model of ours. Multiplied by population,
> that gives person-heat-hours, a unit a health officer already reasons in.
> Degrees are not.
>
> **FortyGuard features used**
>
> Heatmap endpoint with four analytics: `tcm` for the temperature field,
> `exceedance` at eleven thresholds for the ladder, `persistence` for unbroken
> hot stretches, `time_of_measure` for peak hour. Async submit → `activity_id` →
> poll, `api-key` header, 80–100 m granularity. Three districts captured:
> Phoenix, Las Vegas, Tucson.
>
> **Measured result**
>
> A $400,000 budget over central Phoenix selects 60 blocks of cool-roof membrane
> at $393,840, avoiding 18 dangerous heat-hours across 1,827 people — 539
> person-heat-hours. Every figure traces to a source in the report: the cost to
> the EPA's cool-roof compendium, the cooling range to Brousse et al. 2024.
>
> **What it will not claim**
>
> No number in the product originates from a language model. Generated prose is
> checked against the allowed values and discarded if it invents one. The model's
> published metrics say plainly that it does not transfer to a city it has not
> seen (R² −0.009 on a held-out district), that its intervals are wider than
> calibrated (93% against a nominal 80%), and that two features have no citable
> source — so an intervention acting only through them is predicted to do exactly
> nothing. Those statements are served from the model's own metrics file, not
> written by hand, so a retrain cannot leave a stale reassurance on the page.

---

## AI-tool disclosure

CoolRx was built with **Claude Code (Anthropic)** used extensively throughout:
architecture, implementation, debugging, test authoring and documentation. The
commit history reflects that — it is a working record, not a reconstruction.

What the tool did **not** do, by design:

* **No figure in the product is model-generated.** Unit costs and effect sizes
  come from published sources read directly — the EPA cool-roof compendium, a
  Sika durability study, Locke et al. 2024 and Brousse et al. 2024. Where a
  source could not be read (the Brousse paper is paywalled; the figures come from
  UCL's own release about it) the citation says so.
* **Two intervention categories were left out** rather than filled with plausible
  numbers. `shade` and `water` have no tile-scale air-temperature effect that
  could be sourced honestly; the reasoning is recorded in
  `backend/data/CATALOG-RESEARCH.md`.
* **Two model features are null** for the same reason. `albedo_proxy` and
  `openness_proxy` have no citable source, and the consequence is published
  rather than hidden.
* **`agent/numeric_guard.py` enforces this at runtime**, comparing every numeral
  in generated text against the values the backend supplied and rejecting the
  output if it invents one.

Direction, judgement calls and every decision about what would and would not be
claimed were the author's.

---

## Checklist

- [ ] Live demo URL — deploy via `infra/railway.md`
- [ ] Video ≤ 3 min — script at `docs/DEMO_SCRIPT.md`
- [ ] Add `hackathon@fortyguard.com` as repo collaborator
- [ ] Paste the description above into the form
- [ ] Paste the AI disclosure
- [ ] Submit before **30 Aug, 11:59 PM GST** — aim for the 29th
