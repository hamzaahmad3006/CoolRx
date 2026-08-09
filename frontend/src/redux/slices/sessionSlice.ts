import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { FG_LIMITS } from '@/constants';
import type { DataMode, FgGranularity, SessionState } from '@/types';

/**
 * The data mode must agree with how the app is actually running. When fixtures
 * are enabled, the top-bar badge has to read "Fixture data" — a badge claiming
 * "Live" over fixture numbers is exactly the confusion FR-022 forbids.
 */
const INITIAL_DATA_MODE: DataMode =
  process.env.NEXT_PUBLIC_USE_FIXTURES === 'true' ? 'fixture' : 'live';

/**
 * Default measurement window. A hot summer afternoon is the meaningful case for
 * heat analysis, so the defaults land there rather than on "today, now".
 */
const initialState: SessionState = {
  currentProjectId: null,
  currentPlanId: null,
  dataMode: INITIAL_DATA_MODE,
  startDate: '2025-07-15',
  startTime: '15:00',
  granularity: FG_LIMITS.defaultGranularity,
  thresholdC: FG_LIMITS.defaultThresholdC,
  activeJobId: null,
};

const sessionSlice = createSlice({
  name: 'session',
  initialState,
  reducers: {
    setCurrentProject(state, action: PayloadAction<string | null>) {
      state.currentProjectId = action.payload;
      // A different project invalidates the active plan and job.
      state.currentPlanId = null;
      state.activeJobId = null;
    },
    setCurrentPlan(state, action: PayloadAction<string | null>) {
      state.currentPlanId = action.payload;
    },
    setDataMode(state, action: PayloadAction<DataMode>) {
      state.dataMode = action.payload;
    },
    setStartDate(state, action: PayloadAction<string>) {
      state.startDate = action.payload;
    },
    setStartTime(state, action: PayloadAction<string>) {
      state.startTime = action.payload;
    },
    setGranularity(state, action: PayloadAction<FgGranularity>) {
      state.granularity = action.payload;
    },
    setThresholdC(state, action: PayloadAction<number>) {
      state.thresholdC = action.payload;
    },
    setActiveJob(state, action: PayloadAction<string | null>) {
      state.activeJobId = action.payload;
    },
  },
});

export const {
  setCurrentProject,
  setCurrentPlan,
  setDataMode,
  setStartDate,
  setStartTime,
  setGranularity,
  setThresholdC,
  setActiveJob,
} = sessionSlice.actions;

export default sessionSlice.reducer;
