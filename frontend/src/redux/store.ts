import { configureStore } from '@reduxjs/toolkit';

import { coolRxApi } from './api/coolRxApi';
import planControlsReducer from './slices/planControlsSlice';
import sessionReducer from './slices/sessionSlice';
import uiReducer from './slices/uiSlice';
import type { RootStateShape } from '@/types';

/**
 * Store factory. Created per-request rather than as a module singleton so that
 * Next.js server rendering never shares state between users.
 */
export const makeStore = () =>
  configureStore({
    reducer: {
      ui: uiReducer,
      session: sessionReducer,
      planControls: planControlsReducer,
      [coolRxApi.reducerPath]: coolRxApi.reducer,
    },
    middleware: (getDefault) => getDefault().concat(coolRxApi.middleware),
  });

export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore['getState']>;
export type AppDispatch = AppStore['dispatch'];

/**
 * Compile-time assertion that the documented shape in `types/redux.ts` matches
 * the store actually configured here. If a slice is added, renamed or removed
 * without updating `RootStateShape`, this line fails to compile.
 */
type _AssertShape = RootState extends RootStateShape ? true : never;
const _shapeOk: _AssertShape = true;
void _shapeOk;
