import { DISCLAIMER } from '@/constants';
import type { Plan, PlanItem } from '@/types';

/**
 * Prescription fixture.
 *
 * Mirrors the backend's `FIXTURE_MODE` (SRS FR-022) so the UI is fully
 * demonstrable before the API exists, and so a reviewer can run the app with no
 * credentials. Values match the approved Google Stitch mockup for this screen.
 *
 * ⚠️ Fixture data. Not a measurement. The UI surfaces this via the
 * "Fixture data" badge in the top bar, which is deliberately impossible to
 * confuse with live mode.
 */

const MODEL_VERSION = 'trm-2026.08.22-a3f1';

const ITEMS: readonly PlanItem[] = [
  {
    id: 'pi-01',
    rank: 1,
    tileKey: 'B-492',
    interventionCode: 'street_tree_medium',
    interventionName: 'Street trees',
    category: 'green',
    quantity: 127,
    unit: 'tree',
    unitCostUsd: 1_500,
    costUsd: 190_500,
    predictedDelta: {
      value: -1.9,
      ciLow: -2.6,
      ciHigh: -1.2,
      unit: 'celsius',
      modelVersion: MODEL_VERSION,
    },
    heatHoursAvoided: 1_240,
    personHeatHoursAvoided: 8_640,
    peopleAffected: 450,
    marginalBenefitPerUsd: 0.04536,
    rationale:
      'Highest exposure-weighted heat dose in the district, with canopy the dominant driver of its anomaly.',
  },
  {
    id: 'pi-02',
    rank: 2,
    tileKey: 'B-104',
    interventionCode: 'bus_stop_canopy',
    interventionName: 'Bus stop canopies',
    category: 'shade',
    quantity: 8,
    unit: 'structure',
    unitCostUsd: 4_200,
    costUsd: 33_600,
    predictedDelta: {
      value: -0.8,
      ciLow: -1.1,
      ciHigh: -0.5,
      unit: 'celsius',
      modelVersion: MODEL_VERSION,
    },
    heatHoursAvoided: 890,
    personHeatHoursAvoided: 4_180,
    peopleAffected: 1_200,
    marginalBenefitPerUsd: 0.12440,
    rationale:
      'Highest ridership exposure per dollar — eight stops with no existing shade at the 16:00 peak.',
  },
  {
    id: 'pi-03',
    rank: 3,
    tileKey: 'B-218',
    interventionCode: 'cool_pavement_seal',
    interventionName: 'Cool pavement seal',
    category: 'material',
    quantity: 4.2,
    unit: 'linear_m',
    unitCostUsd: 25_000,
    costUsd: 105_000,
    predictedDelta: {
      value: -1.2,
      ciLow: -1.5,
      ciHigh: -0.9,
      unit: 'celsius',
      modelVersion: MODEL_VERSION,
    },
    heatHoursAvoided: 2_100,
    personHeatHoursAvoided: 3_970,
    peopleAffected: 850,
    marginalBenefitPerUsd: 0.02000,
    rationale:
      'Impervious surface above 78% with no feasible planting area; albedo is the only available pathway here.',
  },
  {
    id: 'pi-04',
    rank: 4,
    tileKey: 'B-331',
    interventionCode: 'misting_station',
    interventionName: 'Misting station',
    category: 'water',
    quantity: 2,
    unit: 'station',
    unitCostUsd: 12_000,
    costUsd: 24_000,
    predictedDelta: {
      value: -4.5,
      ciLow: -6.0,
      ciHigh: -3.0,
      unit: 'celsius',
      modelVersion: MODEL_VERSION,
    },
    heatHoursAvoided: 420,
    personHeatHoursAvoided: 1_610,
    peopleAffected: 310,
    marginalBenefitPerUsd: 0.18750,
    rationale:
      'Localised relief at a transit plaza with sustained persistence above threshold; effect is highly local.',
  },
];

export const PRESCRIPTION_FIXTURE: Plan = {
  id: 'plan-fixture-01',
  projectId: 'phoenix-encanto',
  budgetUsd: 400_000,
  objective: 'equity_weighted',
  equityLambda: 1.0,
  thresholdC: 35,
  modelVersion: MODEL_VERSION,
  totals: {
    totalCostUsd: 353_100,
    meanDelta: {
      value: -2.3,
      ciLow: -3.0,
      ciHigh: -1.6,
      unit: 'celsius',
      modelVersion: MODEL_VERSION,
    },
    heatHoursAvoided: 5_820,
    personHeatHoursAvoided: 18_400,
    peopleReached: 3_100,
    pctReachedTopSviQuartile: 61,
  },
  items: ITEMS,
  estimateDisclaimer: DISCLAIMER.estimate,
  createdAt: '2026-08-22T14:31:00Z',
};
