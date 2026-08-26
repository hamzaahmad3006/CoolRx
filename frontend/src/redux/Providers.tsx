'use client';

import { useState, type ReactNode } from 'react';
import { Provider } from 'react-redux';

import { makeStore } from './store';

interface ProvidersProps {
  readonly children: ReactNode;
}

/**
 * Client-side Redux boundary.
 *
 * The store is created once per client rather than at module scope, so server
 * rendering cannot leak one user's state into another's request.
 *
 * `useState`'s lazy initialiser, not a ref. Both create the store exactly once,
 * but the ref form has to read `storeRef.current` back during render to pass it
 * down, and a ref's contents are not a render input — React does not track them,
 * so a component that renders from one can miss an update. `useState` holds the
 * same single instance as actual state and hands it straight back.
 */
export function Providers({ children }: ProvidersProps) {
  const [store] = useState(makeStore);

  return <Provider store={store}>{children}</Provider>;
}
