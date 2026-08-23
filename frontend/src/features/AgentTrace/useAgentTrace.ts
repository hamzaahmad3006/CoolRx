'use client';

import { useMemo } from 'react';
import { USE_FIXTURES } from '@/constants';

import { useGetAgentTraceQuery } from '@/redux/api/coolRxApi';
import type { AgentRun, GuardVerdict } from '@/types';

import { AGENT_RUN_FIXTURE } from './agentTrace.fixture';


interface UseAgentTraceArgs {
  readonly runId: string;
}

/** Plain-language reading of the verdict, shown beside the badge. */
export const VERDICT_SUMMARY: Readonly<Record<GuardVerdict, string>> = {
  pass: 'Every number in the generated text matched a value supplied to the model.',
  retried:
    'The model produced a number it was not given. The guard caught it and the '
    + 'text was regenerated.',
  failed:
    'The model kept producing numbers it was not given, so its text was discarded '
    + 'and replaced with a version containing no figures.',
};

interface UseAgentTraceResult {
  readonly run: AgentRun | null;
  readonly isLoading: boolean;
  readonly errorMessage: string | null;
  readonly verdictSummary: string;
  readonly llmNodeCount: number;
  readonly deterministicNodeCount: number;
  /** Share of wall-clock time spent in language-model nodes, 0–1. */
  readonly llmTimeShare: number;
}

export function useAgentTrace({ runId }: UseAgentTraceArgs): UseAgentTraceResult {
  const query = useGetAgentTraceQuery(runId, { skip: USE_FIXTURES });

  const run = useMemo<AgentRun | null>(() => {
    if (USE_FIXTURES) return { ...AGENT_RUN_FIXTURE, id: runId };
    return query.data ?? null;
  }, [runId, query.data]);

  const { llmNodeCount, deterministicNodeCount, llmTimeShare } = useMemo(() => {
    if (run === null) {
      return { llmNodeCount: 0, deterministicNodeCount: 0, llmTimeShare: 0 };
    }
    const llm = run.nodes.filter((node) => node.type === 'llm');
    const total = run.nodes.reduce((sum, node) => sum + node.durationMs, 0);
    const llmTime = llm.reduce((sum, node) => sum + node.durationMs, 0);
    return {
      llmNodeCount: llm.length,
      deterministicNodeCount: run.nodes.length - llm.length,
      llmTimeShare: total > 0 ? llmTime / total : 0,
    };
  }, [run]);

  return {
    run,
    isLoading: !USE_FIXTURES && query.isLoading,
    errorMessage:
      !USE_FIXTURES && query.isError ? 'We couldn’t load this run’s trace.' : null,
    verdictSummary: run === null ? '' : VERDICT_SUMMARY[run.guardVerdict],
    llmNodeCount,
    deterministicNodeCount,
    llmTimeShare,
  };
}
