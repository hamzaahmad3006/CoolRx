import type { Metadata } from 'next';

import { VerificationPage } from '@/features/Verification/VerificationPage';

export const metadata: Metadata = {
  title: 'Verify a plan',
  description:
    'Re-measure treated blocks against untreated controls and compare the observed '
    + 'change with what was predicted.',
};

export default async function Page({
  params,
}: {
  readonly params: Promise<{ readonly planId: string }>;
}) {
  const { planId } = await params;
  return <VerificationPage planId={planId} />;
}
