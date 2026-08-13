import type { Metadata } from 'next';

import { ImpactEquityPage } from '@/features/ImpactEquity/ImpactEquityPage';

export const metadata: Metadata = {
  title: 'Impact and equity',
  description:
    'Who benefits from the plan: cooling benefit by vulnerability decile and by '
    + 'affected group.',
};

export default async function Page({
  params,
}: {
  readonly params: Promise<{ readonly projectId: string }>;
}) {
  const { projectId } = await params;
  return <ImpactEquityPage projectId={projectId} />;
}
