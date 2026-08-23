# CoolRx — frontend

Next.js 16 (App Router, Turbopack) + TypeScript + Redux Toolkit Query + MapLibre.

The backend is in [`../backend`](../backend); the project as a whole is described
in [`../README.md`](../README.md). Running the two together is covered in
[`../docs/LOCAL-TESTING.md`](../docs/LOCAL-TESTING.md).

## Run it

```bash
npm ci
npx next dev -p 3000
```

`.env.local`:

```
NEXT_PUBLIC_USE_FIXTURES=false
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Both are **build-time** values — `NEXT_PUBLIC_*` is inlined into the bundle, so
changing either needs a rebuild, not a restart.

## Fixtures or live

One flag, defined once in [`src/constants/dataMode.ts`](src/constants/dataMode.ts).

**Unset means fixtures.** That is deliberate: a deploy that forgets to configure
this should still demonstrate correctly from committed recordings rather than
point at a backend that may not be there. Going live is an explicit
`NEXT_PUBLIC_USE_FIXTURES=false`.

It used to be defined in eleven places — four asking `=== 'true'`, seven asking
`!== 'false'`. Those agree whenever the variable is set and disagree completely
when it is not, which is the exact condition of a deploy that forgets it: half
the app would have served fixtures and half live data, in one session, with
nothing on screen to say which figures came from where.

## Layout

```
src/
  app/          route entries only — params in, feature component out
  features/     one directory per screen: <Name>Page.tsx + use<Name>.ts + fixture
  components/   shared UI, charts, map layers
  redux/        RTK Query client, slices
  types/        API and domain types
  constants/    colours, copy, layout, data mode
```

The convention worth knowing: **pages hold no state, no data access and no
navigation.** All of it lives in the feature's hook. A page that fetches is a
page that cannot be reasoned about from its props.

## Conventions that carry a reason

**Numbers are formatted once.** `formatNumber` and the `Estimate` component are
the only places a figure becomes text, so the screen and the PDF cannot drift
apart through separate rounding.

**Null renders as an em dash, never as zero.** 0 °C is a measurement and 0 people
is a finding; an unmeasured block is neither. Every stat that can be unmeasured
takes `number | null` for that reason.

**Every predicted value carries its interval.** No component renders a bare point
estimate — a planning figure without its uncertainty invites a decision it cannot
support.

**Units are echoed from the response, never assumed.** The FortyGuard API sends
no `units` field for `tcm`, so temperature displays unitless rather than showing
a °C nobody published.

**Statistics are read through `fgStat` / `fgStatsBlock`, not by property access.**
The docs capitalise the keys in `stats_data`; the live API lower-cases them. Both
name the same measurement, and reading either is not a guess. Reading only the
documented spelling crashed the diagnosis page the first time it met the real
backend.

## Checks

```bash
npx tsc --noEmit     # must be clean
npm run lint
npm run build        # must succeed — it is what deploys
```

`next dev` does **not** type-check `next.config.ts`. The app ran locally for
months while `npm run build` failed on it, because Next 16 removed the `eslint`
config key and nothing in the dev path ever looked. Run the build before you
believe a deploy will work.
