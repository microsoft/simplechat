// bootstrapStore.ts
// Holds the single /api/v2/bootstrap payload: identity, branding, feature flags,
// catalogs and admin navigation. Loaded once at startup; everything downstream reads
// from here rather than refetching.

import { create } from 'zustand';
import { fetchBootstrap } from '../lib/endpoints';
import { ApiError } from '../lib/apiClient';
import type { BootstrapPayload, PromptOption } from '../lib/types';

/**
 * Orders concurrent refreshes so a slower earlier one cannot land after a newer one.
 *
 * Two saves in quick succession issue two refetches, and nothing guarantees the
 * responses arrive in the order the requests left. Without this the interface can settle
 * on the payload from before the second save.
 */
let refreshSequence = 0;

interface BootstrapState {
    data: BootstrapPayload | null;
    loading: boolean;
    error: string | null;
    /** True when the failure was an expired session rather than a server fault. */
    authExpired: boolean;
    load: () => Promise<void>;
    /**
     * Re-read the payload in place, leaving the current interface on screen.
     *
     * Everything the shell draws comes from bootstrap -- the classification banner, the
     * sidebar logo and application title, the feature flags the chat surface branches on
     * -- and it is otherwise fetched only at startup. An administrator who changes any of
     * those has to reload the browser before the change is visible without this.
     */
    refresh: () => Promise<void>;
    /**
     * Put a prompt into the catalog straight away, before a refresh has been round-tripped.
     *
     * The composer's picker and its `/` menu read `catalogs.prompts`, which is built server-side
     * and cached. Saving a prompt from a chat message bumps that cache, but the payload in hand
     * is still the old one until the refetch lands -- and the whole point of saving from chat is
     * to use the prompt in the message you are writing. Applying it locally makes it selectable
     * immediately; the refresh that follows replaces this with the server's version.
     */
    upsertPromptInCatalog: (prompt: PromptOption) => void;
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

    refresh: async () => {
        const sequence = ++refreshSequence;
        try {
            const data = await fetchBootstrap();
            if (sequence === refreshSequence) {
                set({ data });
            }
        } catch {
            // Advisory on purpose, and the reason this cannot be `load()`. App.tsx
            // replaces the whole interface with the boot screen while `loading` is set
            // and with the boot error when `error` is, so driving either from here would
            // tear down the page being worked on -- unsaved edits included -- over a
            // refetch the reader never asked for. The caller's own write already
            // succeeded, so a briefly stale shell is cosmetic and the next load fixes it.
        }
    },

    upsertPromptInCatalog: (prompt) =>
        set((state) => {
            if (!state.data || !prompt?.id) {
                return state;
            }
            const catalogs = state.data.catalogs ?? {};
            const prompts = (catalogs.prompts ?? []) as PromptOption[];
            const index = prompts.findIndex((item) => item.id === prompt.id);
            const next =
                index === -1
                    ? [...prompts, prompt]
                    : prompts.map((item, at) => (at === index ? { ...item, ...prompt } : item));

            return {
                data: {
                    ...state.data,
                    catalogs: { ...catalogs, prompts: next },
                },
            };
        }),
}));

/** Read a feature flag, defaulting to off when bootstrap has not resolved. */
export function useFeature(key: string): boolean {
    return useBootstrapStore((state) => Boolean(state.data?.features?.[key]));
}
