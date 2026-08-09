import { useDispatch, useSelector, useStore } from 'react-redux';

import type { AppDispatch, AppStore, RootState } from './store';

/**
 * Typed Redux hooks. Always use these — never the untyped `useDispatch` /
 * `useSelector` from react-redux, which would erase the state type.
 */
export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
export const useAppStore = useStore.withTypes<AppStore>();
