/**
 * Provenance fixture for the Cooling Action Plan.
 *
 * Every headline figure in the report must trace to something: a FortyGuard
 * activity id, a catalog citation, a model version, or a named derivation.
 * Principle P2 makes that a requirement rather than a nicety, so the provenance
 * table is part of the report, not an appendix nobody reads.
 *
 * The `value` fields are strings reproducing each figure exactly as displayed,
 * so the table and the report cannot drift apart through separate rounding.
 */

import type { ProvenanceRecord } from '@/types';

const RETRIEVED = '2026-08-22T14:28:00Z';
const MODEL_VERSION = 'trm-2026.08.22-a3f1';

export const PROVENANCE_FIXTURE: readonly ProvenanceRecord[] = [
  {
    figureLabel: 'District mean temperature',
    value: '41.2 °C',
    sourceType: 'fortyguard',
    activityId: 'act_9f2c71b3e4',
    sourceDetail: 'Temperature API · tcm · 80 m · 2025-07-15 15:00 UTC',
    retrievedAt: RETRIEVED,
  },
  {
    figureLabel: 'Hours above 35 °C, district',
    value: '5,820 h',
    sourceType: 'fortyguard',
    activityId: 'act_4a81de20c7',
    sourceDetail: 'Temperature API · exceedance · threshold 35 °C',
    retrievedAt: RETRIEVED,
  },
  {
    figureLabel: 'Hours avoided by this plan',
    value: '1,940 h',
    sourceType: 'derived',
    activityId: 'act_4a81de20c7',
    sourceDetail:
      'Exceedance ladder: hours at 35 °C minus hours at the post-intervention '
      + 'threshold, under a uniform diurnal shift',
    retrievedAt: RETRIEVED,
  },
  {
    figureLabel: 'Predicted mean cooling',
    value: '-2.3 °C (-3.0 to -1.6)',
    sourceType: 'model',
    activityId: null,
    sourceDetail: `Counterfactual inference, model ${MODEL_VERSION}, clamped to cited effect ranges`,
    retrievedAt: RETRIEVED,
  },
  {
    figureLabel: 'Population reached',
    value: '18,400 people',
    sourceType: 'external_dataset',
    activityId: null,
    sourceDetail:
      'US Census ACS block-group population, distributed dasymetrically by '
      + 'building footprint. An estimate, not a count.',
    retrievedAt: RETRIEVED,
  },
  {
    figureLabel: 'Total plan cost',
    value: '$353,100',
    sourceType: 'catalog',
    activityId: null,
    sourceDetail:
      'Sum of quantity × unit cost across selected items; unit costs carry '
      + 'per-intervention citations listed in the appendix.',
    retrievedAt: RETRIEVED,
  },
];
