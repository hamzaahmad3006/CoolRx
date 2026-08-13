import type { Metadata } from 'next';

import { AgentTracePage } from '@/features/AgentTrace/AgentTracePage';

export const metadata: Metadata = {
  title: 'Agent trace',
  description:
    'Node-by-node execution log and the numeric guard verdict for a generated plan.',
};

export default async function Page({
  params,
}: {
  readonly params: Promise<{ readonly runId: string }>;
}) {
  const { runId } = await params;
  return <AgentTracePage runId={runId} />;
}
