'use client';

import { useCallback, useMemo, useState } from 'react';

import {
  useGetVerificationProtocolQuery,
  useRunVerificationMutation,
} from '@/redux/api/coolRxApi';
import type { VerificationProtocol, VerificationResult } from '@/types';

import { PROTOCOL_FIXTURE, RESULT_FIXTURE } from './verification.fixture';

const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES !== 'false';

interface UseVerificationArgs {
  readonly planId: string;
}

export interface DifferenceBreakdown {
  readonly treatedChange: number;
  readonly controlChange: number;
  readonly difference: number;
}

interface UseVerificationResult {
  readonly protocol: VerificationProtocol | null;
  readonly result: VerificationResult | null;
  readonly breakdown: DifferenceBreakdown | null;
  /**
   * How much of the raw treated-block change was ordinary weather, as measured
   * by the controls. The number that justifies the whole design.
   */
  readonly weatherComponentC: number | null;
  readonly isLoading: boolean;
  readonly isRunning: boolean;
  readonly errorMessage: string | null;
  readonly followupDate: string;
  readonly onFollowupDateChange: (date: string) => void;
  readonly onRunVerification: () => void;
}

export function useVerification({
  planId,
}: UseVerificationArgs): UseVerificationResult {
  const protocolQuery = useGetVerificationProtocolQuery(planId, {
    skip: USE_FIXTURES,
  });
  const [runVerification, runState] = useRunVerificationMutation();

  const [followupDate, setFollowupDate] = useState(
    USE_FIXTURES ? PROTOCOL_FIXTURE.scheduledFor : '',
  );
  const [result, setResult] = useState<VerificationResult | null>(
    USE_FIXTURES ? RESULT_FIXTURE : null,
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const protocol = useMemo<VerificationProtocol | null>(() => {
    if (USE_FIXTURES) return { ...PROTOCOL_FIXTURE, planId };
    return protocolQuery.data ?? null;
  }, [planId, protocolQuery.data]);

  /**
   * Decompose the difference-in-differences so the arithmetic is visible.
   *
   * Showing only the final number would ask the reader to trust that the
   * controls were subtracted. Showing both changes lets them check it, and makes
   * the weather component impossible to overlook.
   */
  const breakdown = useMemo<DifferenceBreakdown | null>(() => {
    if (result === null) return null;
    const treatedChange = result.treatedFollowupC - result.treatedBaselineC;
    const controlChange = result.controlFollowupC - result.controlBaselineC;
    return {
      treatedChange,
      controlChange,
      difference: treatedChange - controlChange,
    };
  }, [result]);

  const onRunVerification = useCallback((): void => {
    setErrorMessage(null);

    if (USE_FIXTURES) {
      setResult(RESULT_FIXTURE);
      return;
    }

    void runVerification({ planId, body: { followupDate } })
      .unwrap()
      .then((response) => setResult(response))
      .catch(() =>
        setErrorMessage(
          'We couldn’t complete the re-measurement. The plan and its protocol are unchanged.',
        ),
      );
  }, [followupDate, planId, runVerification]);

  return {
    protocol,
    result,
    breakdown,
    weatherComponentC: breakdown?.controlChange ?? null,
    isLoading: !USE_FIXTURES && protocolQuery.isLoading,
    isRunning: runState.isLoading,
    errorMessage,
    followupDate,
    onFollowupDateChange: setFollowupDate,
    onRunVerification,
  };
}
