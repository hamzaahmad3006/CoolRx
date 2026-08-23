/**
 * Whether the app reads committed fixtures or the live backend.
 *
 * One definition, because there used to be eleven. Four modules asked
 * `=== 'true'` and seven asked `!== 'false'`, which agree whenever the variable
 * is set to either value and disagree completely when it is unset — the exact
 * condition of a deployment that forgets to configure it. Half the app would
 * have served fixtures and the other half live data, in the same session, with
 * nothing to indicate which figures came from where.
 *
 * Unset means fixtures. That is the safe direction for this product: a
 * misconfigured deploy still demonstrates correctly from committed recordings
 * and spends no API credits, where defaulting to live would point the UI at a
 * backend that may not be there. Going live is therefore a deliberate act —
 * `NEXT_PUBLIC_USE_FIXTURES=false` — rather than something that happens by
 * omission.
 *
 * Read at module scope on purpose: `NEXT_PUBLIC_*` values are inlined at build
 * time, so this cannot change at runtime and must not be treated as though it
 * could.
 */
export const USE_FIXTURES: boolean =
  process.env.NEXT_PUBLIC_USE_FIXTURES !== 'false';

/** The inverse, where reading it that way makes a call site clearer. */
export const USE_LIVE_BACKEND: boolean = !USE_FIXTURES;


/**
 * Origin of the backend, for URLs the browser navigates to directly rather than
 * fetching. Kept beside the data-mode flag because the two are always read
 * together, and matches the base `coolRxApi` builds its requests from.
 */
export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
