/**
 * Verification fixture.
 *
 * The observed effect deliberately lands *inside* the predicted interval but
 * below its midpoint — the realistic outcome. A fixture showing the prediction
 * hitting exactly would make the page look like a scoreboard the tool always
 * wins, which is the opposite of what this screen is for.
 *
 * Control blocks warmed slightly between the two dates. That is the whole reason
 * the design subtracts them: without the control, this plan would appear to have
 * delivered 2.5 °C rather than 1.9 °C, and 0.6 °C of ordinary weather variation
 * would have been claimed as intervention effect.
 */

import type { VerificationProtocol, VerificationResult } from '@/types';

const MODEL_VERSION = 'trm-2026.08.22-a3f1';

export const PROTOCOL_FIXTURE: VerificationProtocol = {
  planId: 'plan_2b8e44a1',
  aoi: {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [-112.09, 33.435],
              [-112.06, 33.435],
              [-112.06, 33.46],
              [-112.09, 33.46],
              [-112.09, 33.435],
            ],
          ],
        },
      },
    ],
  },
  granularity: 80,
  startTime: '15:00',
  analyticType: 'tcm',
  scheduledFor: '2027-07-15',
  treatedTileKeys: [
    '9tbq2p3xj', '9tbq2p3xm', '9tbq2p3xq', '9tbq2p3xr', '9tbq2p3xw',
    '9tbq2p60j', '9tbq2p60m', '9tbq2p60q',
  ],
  controlTileKeys: [
    '9tbq2p2yb', '9tbq2p2yc', '9tbq2p2yf', '9tbq2p2yg', '9tbq2p2yu',
    '9tbq2p31b', '9tbq2p31c', '9tbq2p31f',
  ],
  statisticalTest: 'difference_in_differences',
};

export const RESULT_FIXTURE: VerificationResult = {
  treatedBaselineC: 43.1,
  treatedFollowupC: 40.6,
  controlBaselineC: 42.4,
  controlFollowupC: 43.0,
  // (40.6 − 43.1) − (43.0 − 42.4) = −2.5 − 0.6 = −3.1
  observedDeltaC: -3.1,
  predictedDelta: {
    value: -2.3,
    ciLow: -3.4,
    ciHigh: -1.2,
    unit: 'celsius',
    modelVersion: MODEL_VERSION,
  },
  withinCi: true,
  method: 'difference_in_differences',
  caveat:
    'Difference-in-differences against untreated control blocks. Weather, '
    + 'land-use change and measurement conditions differ between the two dates, '
    + 'so this comparison is evidence consistent with the prediction, not proof '
    + 'of cause.',
  measuredAt: '2027-07-15T15:00:00Z',
};
