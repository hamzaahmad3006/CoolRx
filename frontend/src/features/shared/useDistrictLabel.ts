'use client';

import { USE_FIXTURES } from '@/constants';
import { useGetProjectQuery } from '@/redux/api/coolRxApi';
import { useAppSelector } from '@/redux/hooks';

/**
 * The district's name and measurement context, from the project itself.
 *
 * Every route used to pass these as literals: `districtName="Phoenix · Encanto"`
 * and `districtContext="2025-07-15 15:00 · 80 m · 35 °C"`, on all three pages.
 * Encanto was one of the invented preset districts, so opening Las Vegas showed
 * a Phoenix breadcrumb over Las Vegas numbers, and the context line quoted a
 * date, granularity and threshold that had nothing to do with the run on screen.
 *
 * The fixture strings are kept for fixture mode, where they do describe the
 * recorded district.
 */

const FIXTURE_NAME = 'Phoenix · Encanto';
const FIXTURE_CONTEXT = '2025-07-15 15:00 · 80 m · 35 °C';

export interface DistrictLabel {
  readonly districtName: string;
  readonly districtContext: string;
}

export function useDistrictLabel(projectId: string): DistrictLabel {
  const thresholdC = useAppSelector((state) => state.session.thresholdC);
  const startDate = useAppSelector((state) => state.session.startDate);
  const startTime = useAppSelector((state) => state.session.startTime);
  const granularity = useAppSelector((state) => state.session.granularity);

  const { data } = useGetProjectQuery(projectId, {
    skip: USE_FIXTURES || projectId === '',
  });

  if (USE_FIXTURES) {
    return { districtName: FIXTURE_NAME, districtContext: FIXTURE_CONTEXT };
  }

  return {
    // Falls back to a neutral label rather than another district's name. A
    // breadcrumb is a claim about which ground is on screen.
    districtName: data?.name ?? 'District',
    districtContext: `${startDate} ${startTime} · ${granularity} m · ${thresholdC} °C`,
  };
}
