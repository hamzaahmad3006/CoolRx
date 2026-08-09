'use client';

import { useRef, type ReactNode } from 'react';
import { Provider } from 'react-redux';

import { makeStore, type AppStore } from './store';

interface ProvidersProps {
  readonly children: ReactNode;
}

/**
 * Client-side Redux boundary.
 *
 * The store is created once per client via a ref rather than at module scope, so
 * server rendering cannot leak one user's state into another's request.
 */
export function Providers({ children }: ProvidersProps) {
  const storeRef = useRef<AppStore | null>(null);

  if (storeRef.current === null) {
    storeRef.current = makeStore();
  }

  return <Provider store={storeRef.current}>{children}</Provider>;
}
