# Official Slack findings — 2026-08-18

Addendum to `SRS-PRD.md`. **Nothing in the SRS has been overwritten.** This file records what was
verified from the official hackathon Slack, what it changes, and what remains unknown.

Workspace: `fortyguardhackthon26.slack.com` · Captured 2026-08-18 ~11:40 PKT (10:40 GST)

## Source hierarchy used

| Tier | Source | Treatment |
|---|---|---|
| 1 — Authoritative | Pinned canvases in `#announcements`, authored by **Hackathon Team** (U0BKJCU7CM6) | Used as fact |
| 2 — Official | Direct messages from **Hackathon Team** in `#help-general` / `#help-technical` | Used as fact; conflicts reported, not resolved |
| 3 — Unofficial | **FortyGuard Assistant** (U0BKNPDESRJ, a bot) | Recorded as lead only, marked bot-sourced. It self-declares gaps ("the knowledge base doesn't specify") |
| 4 — Ignored | Other participants | Not used |

The FAQ canvas states: *"#announcements … is the single source of truth — anything posted elsewhere is unofficial."*

---

## 1. CONFIRMED — matches what CoolRx already implements

No code change needed. These were assumptions; they are now verified against Tier-1 sources.

| Item | Official value | CoolRx status |
|---|---|---|
| Base URL | `https://api.fortyguard.com` | `config.py:64` → `https://api.fortyguard.com/v1` ✅ |
| Auth | key in **`api-key` header — no OAuth, no Bearer token** | `clients/fortyguard/client.py:198` returns `{"api-key": key}` ✅ |
| Key storage | env var `FORTYGUARD_API_KEY` in a git-ignored `.env` | `.env.example:25` ✅ |
| Async pattern | submit → `activity_id` → poll status endpoint | SRS §11, `workers/pipeline.py` ✅ |
| Poll backoff | official guidance 3s → 6s → 12s | SRS uses 2s → 30s jittered, bounded ✅ compatible |
| Granularity | `60`, `80`, `100` metres | SRS §530 enum ✅ |
| Coverage | **U.S. only** | NG-05 ✅ |
| Polygon rules | `[longitude, latitude]`, closed ring | SRS validation layer ✅ |
| Premium endpoints | satellite, streetview, heat_intelligence — auth error without the right plan | All behind flags, never on MVP path ✅ |
| Failed calls | do **not** consume credits | ✅ |
| Judging weights | Impact 40 / Technical 35 / Innovation 15 / Communication 10 | ✅ |
| Deadline | **30 Aug 2026, 11:59 PM GST**, hard close | ✅ |

## 2. RESOLVED — open questions the Slack canvases now answer

### Q-01 / C-1 — historical date floor → **2021-01-01 CONFIRMED**

FAQ canvas: *"All date and time inputs must fall between **2021-01-01** and the present day."*

The SRS flagged a conflict between the API docs (2019-01-01) and the FAQ (2021-01-01) and defaulted to
the stricter bound. **That default is correct.** `FG_DATE_FLOOR=2021-01-01` stands. Q-01 can be closed
without spending a Day-1 verification call.

### Q-02 / C-2 — does `filter_type=4` exist? → **YES**

FAQ canvas: *"`filter_type` 1 = a single hour, 2 = a range of hours within the same day, 3 = an entire
day, 4 = **a date range up to about a month (heatmaps only)**."*

SRS §11 currently constrains `filter_type ∈ {1, 2, 3}`. Officially there are **four**, with 4 restricted
to heatmaps. This is the cheap-harvest path the SRS hoped for — one call per month rather than per hour.
Still needs an empirical check that it is enabled on the hackathon plan.

### Q-16 — is a video or written description required? → **YES, BOTH**

SRS §3788 records this as *"NOT SPECIFIED — the FAQ names three items only."* **The FAQ canvas now names
four:**

1. A live **demo link**
2. A **video, max 3 minutes**, showing the project working
3. **Code on GitHub** with the judge account added as collaborator
4. A **brief description, max 500 words** — problem → who it's for → FortyGuard endpoints/features used → measured result

Item 4 is not currently in the SRS submission checklist (§24.8, §3903, §3939).

## 3. DISCREPANCIES in the current SRS — recommend correcting

**Not yet applied.** These are substantive, so they are listed for approval rather than edited in.

| # | SRS says | Official says | Risk |
|---|---|---|---|
| D-1 | Add **`fortyguard`** as collaborator (§198, §3052, §3546, §3659, §3700, §3922, §3939, §4017) | Add **`Hackathon-FG` (hackathon@fortyguard.com)** | **High** — judges may be unable to access the repo |
| D-2 | *"Make the repository public"* (§3659, §3052) | Repo **may stay private**; the collaborator invite is what grants judge access | Low — stricter than required, but forces avoidable disclosure |
| D-3 | Submission = repo + live demo + collaborator (3 items) | **4 items** incl. video and ≤500-word description | **High** — an incomplete submission |
| D-4 | Heatmap AOI ≤ **10 mi²** on Basic, 50 mi² only if Premium (§533, §3189) | FAQ gives a single heatmap size limit of *"roughly 130 km² / 50 mi²"* with **no plan-tier qualifier** | Medium — the 10 mi² cap may be unnecessarily tight, but the FAQ does not mention tiers at all, so **do not raise the cap without testing** |

## 4. STILL UNKNOWN — no official answer found in Slack

| # | Question | Status |
|---|---|---|
| Q-04 / C-8 | Which plan tier do hackathon participants get (Basic / Premium / Startup)? | **Unknown.** The bot said explicitly: *"the knowledge base doesn't specify exactly which plan tier the hackathon trial includes"* and referred it to the organisers. Keep Premium behind flags. |
| Q-05 / C-9 | Credits consumed per heatmap call, per granularity | **Unknown.** FAQ confirms credits exist and failed calls are free, but publishes no per-call cost. |
| Q-07 / C-10 | Exact credits-usage endpoint path | **Bot-sourced only:** `POST /v1/system/fetch-api-key-usage`. Not confirmed by any canvas. FAQ only says "the credits-usage endpoint (also in notebook 00 of the Quickstart)". **Do not hard-code from the bot** — read it from notebook 00. |
| Q-08 / C-11 | Published rate limits | **Unknown.** Not mentioned in either canvas. |
| — | Total trial credit allocation | **Unknown.** |

## 5. API access status as at 2026-08-18 10:40 GST

**API key access has NOT been announced as live.**

- The build window opened 18 Aug 2026 at 12:00 AM GST (FAQ canvas).
- The most recent `#announcements` post is **17 Aug 12:48 PKT**: *"API key access opens **tomorrow**."*
- `#announcements` contains **no post today**. The canvas promises: *"When it's live, we'll post here in #announcements and email you with the exact steps."*
- Organisers were actively replying elsewhere in Slack at 11:31–11:37 PKT today — they are online (working hours **10:00–19:00 GST**) but have not announced key availability.

**Documented route once it opens** (canvas + repeated organiser messages): sign in at
`dashboard.fortyguard.com` → **Profile** tab → generate API key (issued with trial credits).

Until then the SRS's `FIXTURE_MODE` / cached-fixture path is the correct posture, and matches the
organisers' own advice to develop against the Quickstart's `CACHED=True` mode.

## 6. Official resources

| Resource | URL |
|---|---|
| API documentation | https://docs-api.fortyguard.com/docs |
| Dashboard | https://dashboard.fortyguard.com/ |
| Quickstart repo | https://github.com/FortyGuard-Tech/temperature-api-quickstart |
| Participant handbook | https://drive.google.com/file/d/1GPAke_0Nez8vaRFs_gqzUsZmQoptsjL3/view |
| Event page | https://www.fortyguard.com/hackathon26 |
| Technical support | support@fortyguard.com |
| Everything else | hackathon@fortyguard.com |

Quickstart notebooks: 00 auth check · 01 first heatmap · 02 env parameters · 03 satellite (Premium) ·
04 street view (Premium) · 05 heat intelligence (Premium). All ship with `CACHED=True`.

## 7. Analytics vocabulary (FAQ canvas §6) — confirms CoolRx naming

Map analytics: **Time of Measure**, **Exceedance**, **Persistence**. Chart views: **Time Series**,
**Distribution**. CoolRx already submits `tcm`, `exceedance`, `persistence`, `time_of_measure`
(SRS §292) — consistent.

## 8. Unresolved CONFLICT — solo participation

Two official organiser positions exist, from the **same** account. Reported, not resolved.

**Position A — solo requires no action:**
- 17 Aug 14:19 (#help-technical): *"you don't need to fill out the team form (that's just for team leaders), so there's nothing you need to update — just keep building and submit under your own name"*
- 17 Aug 17:08 (#help-general): same wording
- 17 Aug 18:58 (#help-general): *"you do not require the fill out the form if you are participating solo"*
- 17 Aug 19:31 (#help-general): *"If you are solo then you are good!"*

**Position B — solo requires notifying organisers:**
- 17 Aug 16:24 (#help-technical): *"you can even proceed solo and you can update us that you will be participating solo"*
- 17 Aug 16:39 (#introductions): *"you can also proceed solo by **informing us directly**"*
- 18 Aug 11:35 (#help-general, ×3 — the **most recent**): *"you could continue solo just email hackathon@fortyguard.com"*

**Observable context difference (not an official statement):** the Position B replies were all in threads
from people whose pre-registered teams had fallen apart, i.e. leaving an existing roster. Position A
replies were to people who were solo from the outset. This is a plausible reconciliation but **has not
been confirmed by any organiser**, so it must not be treated as settled.

A separate **Team Registration Form** (https://forms.gle/CCCvSNgDsDiNZ2gk7) was posted to
`#announcements` on 17 Aug 19:50, addressed to *"Team leader"*. The bot had earlier claimed no separate
team-registration form exists — the bot was wrong.
