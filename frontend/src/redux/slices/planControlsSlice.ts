import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import type { PlanControlsState, PlanObjective } from '@/types';

const initialState: PlanControlsState = {
  budgetUsd: 400_000,
  objective: 'equity_weighted',
  /** λ = 1.0. A policy choice, surfaced and labelled as one in the UI. */
  equityLambda: 1.0,
};

const planControlsSlice = createSlice({
  name: 'planControls',
  initialState,
  reducers: {
    setBudgetUsd(state, action: PayloadAction<number>) {
      state.budgetUsd = Math.max(0, action.payload);
    },
    setObjective(state, action: PayloadAction<PlanObjective>) {
      state.objective = action.payload;
    },
    /** Equity weight, clamped to the 0–2 range exposed by the slider. */
    setEquityLambda(state, action: PayloadAction<number>) {
      state.equityLambda = Math.min(2, Math.max(0, action.payload));
    },
    resetPlanControls() {
      return initialState;
    },
  },
});

export const {
  setBudgetUsd,
  setObjective,
  setEquityLambda,
  resetPlanControls,
} = planControlsSlice.actions;

export default planControlsSlice.reducer;
