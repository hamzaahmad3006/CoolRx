/**
 * Equity fixture.
 *
 * Shaped so the distribution is *not* flat — decile 10 (most vulnerable) receives
 * a disproportionate share, which is what an equity-weighted plan should produce
 * and what the page needs to be able to show. A uniform fixture would make the
 * chart look correct while proving nothing about whether it renders a real
 * distribution.
 *
 * Decile 3 deliberately has no benefit at all: not every part of a district is
 * treated, and the page must show a zero honestly rather than smoothing it.
 */

import type { EquityDecile, VulnerableGroupBreakdown } from '@/types';

export const EQUITY_DECILES_FIXTURE: readonly EquityDecile[] = [
  { decile: 1, population: 4_120, personHeatHours: 21_400, personHeatHoursAvoided: 340, shareOfBenefit: 0.018 },
  { decile: 2, population: 3_880, personHeatHours: 23_100, personHeatHoursAvoided: 510, shareOfBenefit: 0.028 },
  { decile: 3, population: 4_310, personHeatHours: 26_800, personHeatHoursAvoided: 0, shareOfBenefit: 0.0 },
  { decile: 4, population: 4_050, personHeatHours: 29_400, personHeatHoursAvoided: 890, shareOfBenefit: 0.048 },
  { decile: 5, population: 4_460, personHeatHours: 33_200, personHeatHoursAvoided: 1_240, shareOfBenefit: 0.067 },
  { decile: 6, population: 4_720, personHeatHours: 37_900, personHeatHoursAvoided: 1_680, shareOfBenefit: 0.091 },
  { decile: 7, population: 5_010, personHeatHours: 43_600, personHeatHoursAvoided: 2_240, shareOfBenefit: 0.122 },
  { decile: 8, population: 5_380, personHeatHours: 51_200, personHeatHoursAvoided: 3_010, shareOfBenefit: 0.164 },
  { decile: 9, population: 5_640, personHeatHours: 58_700, personHeatHoursAvoided: 3_890, shareOfBenefit: 0.211 },
  { decile: 10, population: 5_930, personHeatHours: 67_300, personHeatHoursAvoided: 4_600, shareOfBenefit: 0.250 },
];

export const VULNERABLE_GROUPS_FIXTURE: readonly VulnerableGroupBreakdown[] = [
  {
    group: 'Residents over 65',
    populationReached: 3_180,
    shareOfGroupReached: 0.41,
    personHeatHoursAvoided: 5_720,
  },
  {
    group: 'Households below the poverty line',
    populationReached: 5_140,
    shareOfGroupReached: 0.52,
    personHeatHoursAvoided: 8_410,
  },
  {
    group: 'Blocks with a school or playground',
    populationReached: 2_260,
    shareOfGroupReached: 0.34,
    personHeatHoursAvoided: 3_090,
  },
  {
    group: 'Blocks with a transit stop',
    populationReached: 6_890,
    shareOfGroupReached: 0.58,
    personHeatHoursAvoided: 9_940,
  },
];
