/**
 * Fixture for the agent trace.
 *
 * Deliberately shows a run where the guard **caught a violation and retried**,
 * not a spotless one. A trace page that only ever displays "pass" proves nothing —
 * the whole reason the page exists is to show the mechanism working, and a reader
 * can only judge that if they see it fire.
 */

import type { AgentRun, ModelValidation } from '@/types';

const MODEL_VERSION = 'trm-2026.08.22-a3f1';

export const AGENT_RUN_FIXTURE: AgentRun = {
  id: 'run_7f3a19c4',
  planId: 'plan_2b8e44a1',
  graphVersion: 'coolrx-graph-1.2',
  model: 'claude-opus-5',
  guardVerdict: 'retried',
  nodes: [
    {
      name: 'load_plan',
      type: 'deterministic',
      durationMs: 42,
      tokensIn: null,
      tokensOut: null,
    },
    {
      name: 'assemble_evidence',
      type: 'deterministic',
      durationMs: 118,
      tokensIn: null,
      tokensOut: null,
    },
    {
      name: 'draft_rationales',
      type: 'llm',
      durationMs: 4_310,
      tokensIn: 3_820,
      tokensOut: 1_140,
    },
    {
      name: 'numeric_guard',
      type: 'deterministic',
      durationMs: 8,
      tokensIn: null,
      tokensOut: null,
    },
    {
      name: 'compose_report',
      type: 'llm',
      durationMs: 6_020,
      tokensIn: 5_410,
      tokensOut: 2_260,
    },
  ],
  guardViolations: [
    {
      node: 'draft_rationales',
      token: '850',
      context:
        '…shading the transit stop would reach roughly 850 daily riders in this block…',
      reason:
        'The value 850 was not supplied to the model. Only values passed as structured input may appear.',
    },
  ],
  tokensIn: 9_230,
  tokensOut: 3_400,
  durationMs: 10_498,
  createdAt: '2026-08-22T14:31:07Z',
};

export const MODEL_VALIDATION_FIXTURE: ModelValidation = {
  modelVersion: MODEL_VERSION,
  trainingTileCount: 48_120,
  trainingDistricts: ['Phoenix, AZ', 'Las Vegas, NV', 'Tucson, AZ'],
  heldOutDistricts: ['Mesa, AZ'],
  maeC: 0.82,
  r2: 0.71,
  intervalCoverage: 0.79,
  features: [
    'canopy_pct',
    'impervious_pct',
    'building_pct',
    'water_pct',
    'grass_shrub_pct',
    'albedo_proxy',
    'openness_proxy',
    'elevation_m',
    'local_relief_m',
    'dist_to_water_m',
    'hour_utc',
    'doy',
    'latitude',
  ],
  limitations: [
    'Trained on three arid south-western US districts. Predictions for humid or '
      + 'temperate cities are extrapolation and should not be relied on.',
    'Held out by district rather than by random tile. Neighbouring tiles are '
      + 'strongly correlated, so a random split would report an accuracy the model '
      + 'does not have on a new city.',
    'Openness is derived from OpenStreetMap building-footprint density, not from '
      + 'building heights. It is a proxy for street-canyon geometry, not a '
      + 'sky-view factor.',
    'Social Vulnerability Index is published per census tract, coarser than the '
      + 'analysis blocks, so within-tract variation is not represented.',
    'The model predicts a temperature field. It does not establish that any '
      + 'intervention caused a change; verification is a separate measurement.',
  ],
};
