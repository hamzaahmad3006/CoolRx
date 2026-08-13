import type { Metadata } from 'next';

import { ActionPlanPage } from '@/features/ActionPlan/ActionPlanPage';

export const metadata: Metadata = {
  // The root layout appends "· CoolRx" via its title template.
  title: 'Cooling Action Plan',
  description:
    'The costed intervention schedule, its predicted impact with uncertainty, the '
    + 'measurement protocol, and the provenance of every figure.',
};

export default async function Page({
  params,
}: {
  readonly params: Promise<{ readonly planId: string }>;
}) {
  const { planId } = await params;
  return <ActionPlanPage planId={planId} />;
}
