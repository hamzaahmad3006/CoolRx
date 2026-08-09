import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import type { FgAnalyticType } from '@/types';
import type { ThemeMode, UiState } from '@/types';

const initialState: UiState = {
  theme: 'light',
  railCollapsed: false,
  rightPanelOpen: true,
  selectedTileKey: null,
  attributionDrawerOpen: false,
  activeAnalytic: 'tcm',
  swipePosition: 0.5,
  degradedBannerDismissed: false,
};

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    setTheme(state, action: PayloadAction<ThemeMode>) {
      state.theme = action.payload;
    },
    toggleTheme(state) {
      state.theme = state.theme === 'light' ? 'dark' : 'light';
    },
    toggleRail(state) {
      state.railCollapsed = !state.railCollapsed;
    },
    setRightPanelOpen(state, action: PayloadAction<boolean>) {
      state.rightPanelOpen = action.payload;
    },
    /** Selecting a tile opens the attribution drawer. */
    selectTile(state, action: PayloadAction<string>) {
      state.selectedTileKey = action.payload;
      state.attributionDrawerOpen = true;
    },
    closeAttributionDrawer(state) {
      state.attributionDrawerOpen = false;
      state.selectedTileKey = null;
    },
    setActiveAnalytic(state, action: PayloadAction<FgAnalyticType>) {
      state.activeAnalytic = action.payload;
    },
    /** Swipe divider on Before/After. Clamped to 0–1. */
    setSwipePosition(state, action: PayloadAction<number>) {
      state.swipePosition = Math.min(1, Math.max(0, action.payload));
    },
    dismissDegradedBanner(state) {
      state.degradedBannerDismissed = true;
    },
  },
});

export const {
  setTheme,
  toggleTheme,
  toggleRail,
  setRightPanelOpen,
  selectTile,
  closeAttributionDrawer,
  setActiveAnalytic,
  setSwipePosition,
  dismissDegradedBanner,
} = uiSlice.actions;

export default uiSlice.reducer;
