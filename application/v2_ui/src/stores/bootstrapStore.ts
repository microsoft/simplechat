// bootstrapStore.ts
// Holds the single /api/v2/bootstrap payload: identity, branding, feature flags,
// catalogs and admin navigation. Loaded once at startup; everything downstream reads
// from here rather than refetching.

import { create } from 'zustand';
import { fetchBootstrap } from '../lib/endpoints';
import { ApiError } from '../lib/apiClient';
import type { BootstrapPayload } from '../lib/types';

interface BootstrapState {
    data: BootstrapPayload | null;
    loading: boolean;
    error: string | null;
    /** True when the failure was an expired session rather than a server fault. */
    authExpired: boolean;
    load: () => Promise<void>;
}

export const useBootstrapStore = create<BootstrapState>((set) => ({
    data: null,
    loading: true,
    error: null,
    authExpired: false,

    load: async () => {
        set({ loading: true, error: null, authExpired: false });
        try {
            const data = await fetchBootstrap();
            set({ data, loading: false });
        } catch (error) {
            const isAuthError = error instanceof ApiError && error.isAuthError;
            set({
                loading: false,
                authExpired: isAuthError,
                error:
                    error instanceof Error
                        ? error.message
                        : 'Failed to load the application.',
            });
        }
    },
}));

/** Read a feature flag, defaulting to off when bootstrap has not resolved. */
export function useFeature(key: string): boolean {
    return useBootstrapStore((state) => Boolean(state.data?.features?.[key]));
}
