/**
 * CoolRx user-facing copy — centralised on purpose.
 *
 * SRS §20.5 defines prohibited vs required phrasing around causality, and §27.6
 * mandates a plain-language explanation for every non-obvious term. Keeping the
 * strings in one module means the language rules can be reviewed (and linted) in
 * one place instead of being scattered across twelve pages.
 *
 * Do not write a disclaimer inline in a component. Add it here.
 */

/* ─────────────────────────────────────────────────────────────────────────────
 * MANDATORY DISCLAIMERS — required wherever the referenced value is displayed
 * ────────────────────────────────────────────────────────────────────────────*/
export const DISCLAIMER = {
  /** Must accompany every predicted ΔT and every impact figure. */
  estimate:
    'Planning-grade estimate. Model-based projection under a uniform diurnal shift assumption — not a causal guarantee.',

  /** Attribution drawer header note. */
  attribution:
    'Statistically associated drivers of this block’s temperature anomaly — not proven causes.',

  /** Must sit adjacent to the verification result, not in a footnote. */
  verification:
    'This compares two measurements. Differences may reflect weather variation rather than intervention effect. Control-block differencing reduces but does not eliminate this confound.',

  /** Exceedance-ladder impact conversion. */
  impactConversion:
    'Impact conversion assumes the intervention shifts the block’s whole hourly temperature series down uniformly by ΔT. In reality cooling varies by hour — vegetation cools most at midday and can slightly reduce night-time cooling. This is a first-order approximation.',

  /** Population figures. */
  population:
    'Population is a dasymetric estimate distributed from census block groups by building footprint. It is not a count.',

  /** Social vulnerability resolution. */
  vulnerability:
    'Social vulnerability is census-tract resolution — coarser than the analysis blocks shown.',

  /** Equity weight is a value judgement, not a constant. */
  equityLambda: 'A policy choice, not a scientific constant.',

  /** Shown on the Methods page and in the report. */
  humanReview:
    'CoolRx is a decision-support tool, not a decision-making system. Its outputs are planning-grade estimates intended to inform professional judgement. Site-specific engineering feasibility, utility conflicts, tree-species suitability, soil and irrigation capacity, maintenance capacity, community consultation, and legal or procurement requirements are outside its scope and must be assessed by qualified professionals before any intervention is commissioned.',

  /** Model limitations — reproduced verbatim in the report appendix and README. */
  modelLimitations: [
    'The model learns statistical association between urban form and the measured temperature field. It is not a physics simulation and does not establish causation.',
    'Intervening on a feature yields a model-based counterfactual under a stationarity assumption: a block whose canopy is raised to X is assumed to behave like existing blocks that already have canopy X and are otherwise similar.',
    'Known confounders: canopy correlates with income, building age, irrigation, and street width. The model cannot separate these from canopy’s direct effect.',
    'Labels are produced by FortyGuard’s own models. CoolRx therefore learns the response function implied by that field, and accuracy is reported against held-out FortyGuard blocks — not against independent ground truth.',
    'Outputs are planning-grade estimates, intended to rank and size interventions, not to guarantee a delivered temperature.',
  ],
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * GLOSSARY — tooltip text for every non-obvious term (SRS §27.6)
 * ────────────────────────────────────────────────────────────────────────────*/
export const GLOSSARY = {
  exceedanceHours:
    'Number of hours this block was above the danger threshold on this date.',
  persistence:
    'The longest unbroken stretch of hours above the threshold. Continuous exposure matters more than a brief peak.',
  peakHour:
    'The hour of day when this block reaches its highest temperature. Shown in local time, converted from UTC.',
  personHeatHours:
    'People multiplied by dangerous hours. It measures how much dangerous heat exposure is happening to people here.',
  equityWeight:
    'A policy choice, not a scientific constant. Higher values give more priority to socially vulnerable areas.',
  attribution:
    'Statistically associated drivers of this block’s temperature anomaly — not proven causes.',
  predictedDelta:
    'Planning-grade estimate from a model trained on measured temperature. The range shows model uncertainty.',
  provenance: 'Where this number came from.',
  predictionInterval:
    'Based on model uncertainty, the true effect is expected to fall in this range about 8 times out of 10.',
  granularity:
    'Size of each analysis block. The temperature API supports 60, 80 or 100 metres.',
  threshold:
    'The temperature above which heat is counted as dangerous. Used for exceedance and persistence.',
  marginalBenefit:
    'Cooling delivered per dollar spent. The optimizer selects interventions in this order.',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * EMPTY STATES (SRS §27.4)
 * ────────────────────────────────────────────────────────────────────────────*/
export const EMPTY_STATE = {
  noProject: {
    message: 'Start with a district.',
    hint: 'Load a preset or place an area of interest.',
    action: 'Open a district',
  },
  noDiagnosis: {
    message: 'No measurements yet.',
    hint: 'Choose a date and hour, then run diagnosis.',
    action: 'Run diagnosis',
  },
  noHotspots: {
    message: 'No blocks exceed the threshold for this date and hour.',
    hint: 'Try a hotter afternoon, or lower the threshold.',
    action: 'Adjust settings',
  },
  noPlan: {
    message: 'No plan yet.',
    hint: 'Set a budget and press Prescribe.',
    action: 'Prescribe',
  },
  budgetTooSmall: {
    message: 'No single intervention fits this budget.',
    hint: 'Raise the budget to fund at least one action.',
    action: 'Raise budget',
  },
  noFeasibleCandidates: {
    message: 'No interventions are feasible in this district’s hottest blocks.',
    hint: 'Feasibility rules excluded every candidate — see the reason column.',
    action: 'Review constraints',
  },
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * ERROR & DEGRADED STATES (SRS §27.5)
 * Plain language first, cause second, action third. Never a status code as the
 * headline, never a stack trace.
 * ────────────────────────────────────────────────────────────────────────────*/
export const ERROR_COPY = {
  upstreamUnavailable: {
    message: 'We couldn’t reach the temperature service.',
    hint: 'It may be busy. Your cached districts still work.',
    action: 'Retry',
  },
  timeout: {
    message: 'This analysis took longer than expected.',
    hint: 'The task may still be running upstream. Retrying is free — results are cached.',
    action: 'Retry',
  },
  validation: {
    message: 'That area of interest can’t be analysed.',
    hint: 'Check the size, location and date against the limits shown.',
    action: 'Adjust',
  },
  creditsLow: {
    message: 'Live analysis is paused to protect the remaining API budget.',
    hint: 'Preset districts remain fully available.',
    action: 'Open a preset',
  },
  generic: {
    message: 'Something went wrong.',
    hint: 'Copy the reference below if you need to report it.',
    action: 'Retry',
  },
} as const;

export const BANNER = {
  degraded:
    'Live analysis unavailable — showing cached results for this district.',
  fixture: 'Fixture data — this instance is running from committed fixtures.',
  creditsLow:
    'API credit reserve reached. Live analysis is disabled; cached districts are unaffected.',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * BRAND
 * ────────────────────────────────────────────────────────────────────────────*/
export const BRAND = {
  name: 'CoolRx',
  tagline: 'Prescription-grade urban cooling intelligence',
  heroHeadline: 'Turn street-level temperature into a costed cooling plan.',
  heroSubline:
    'CoolRx reads hyperlocal temperature data, finds the blocks that are dangerously hot, explains why, and prescribes what to build — with a plan to verify it worked.',
  workflow: [
    'Measure',
    'Diagnose',
    'Understand',
    'Prioritize',
    'Prescribe',
    'Optimize',
    'Quantify',
    'Report',
    'Verify',
  ],
  attribution: '© OpenStreetMap contributors · Temperature data © FortyGuard',
} as const;

/**
 * Phrasings that must never appear in UI copy, the report, or a prompt template.
 * Checked by `npm run lint:copy` (SRS §20.5).
 */
export const PROHIBITED_PHRASINGS: readonly string[] = [
  'will reduce',
  'will lower',
  'caused the cooling',
  'proven to save',
  'guaranteed',
  'verified effective',
  'proves that',
] as const;
