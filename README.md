# CoolRx

**Prescription-grade urban cooling intelligence.**

CoolRx reads hyperlocal street-level temperature data, finds the blocks that are
dangerously hot, explains why, prescribes what to build under a budget, predicts the
temperature reduction with an uncertainty range, and produces a procurement-ready
Cooling Action Plan — with a pre-registered plan to verify it worked.

Built for **FortyGuard Hackathon '26 — "Building the World's Temperature AI"**.

> 🚧 Under active development. See [`SRS-PRD.md`](SRS-PRD.md) for the full
> specification (36 sections + 10 ADRs).

---

## Workflow

```
Measure → Diagnose → Understand → Prioritize → Prescribe → Optimize → Quantify → Report → Verify
```

## Repository layout

```
CoolRx/
├── SRS-PRD.md          # full specification — the source of truth
├── frontend/           # Next.js 16 · React 19 · TypeScript · Tailwind v4
│   └── src/
│       ├── app/        # App Router — thin route files only
│       ├── features/   # one folder per screen: <Screen>Page.tsx + use<Screen>.ts
│       ├── components/ # shared component library
│       ├── constants/  # colors, typography, spacing, icons, theme
│       ├── types/      # all TypeScript interfaces
│       ├── redux/      # Redux Toolkit + RTK Query
│       ├── api/        # API client
│       └── assets/
└── backend/            # FastAPI · PostgreSQL + PostGIS · Redis + RQ
    ├── main.py
    ├── routes/         # FastAPI routers
    ├── controllers/    # service layer
    ├── middleware/
    ├── clients/        # fortyguard/ · llm/
    ├── repositories/   # all SQL
    ├── ml/             # LightGBM + SHAP
    ├── optimizer/      # budget optimizer
    ├── geo/            # zonal stats, dasymetric downscaling
    ├── agent/          # LangGraph + numeric_guard
    └── report/         # Cooling Action Plan PDF
```

## Architecture conventions

**Every screen is a folder** containing exactly two things: a `.tsx` file holding
only UI, and a `use<Screen>.ts` hook holding all state, validation, API calls and
business logic.

```
src/features/Prescription/
    PrescriptionPage.tsx    # UI only
    usePrescription.ts      # all logic
```

Routes are thin re-exports so Next.js file-system routing still works:

```
src/app/p/[projectId]/prescribe/page.tsx  →  imports PrescriptionPage
```

**Strict TypeScript.** No `any`, no `unknown`. Every variable, prop, API
request/response, Redux slice and model is typed. Design tokens are imported from
`src/constants/` — never hardcoded.

## Status

| Area | State |
|---|---|
| Specification | ✅ complete |
| UI design (Google Stitch) | ✅ 11 of 12 pages |
| Frontend scaffold | 🚧 in progress |
| Backend scaffold | ⬜ not started |
| FortyGuard integration | ⬜ not started |

## License

MIT
