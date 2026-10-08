// bootstrapStore.ts
// Holds the single /api/v2/bootstrap payload: identity, branding, feature flags,
// catalogs and admin navigation. Loaded once at startup; everything downstream reads
// from here rather than refetching.

import { create } from 'zustand';
import { fetchActiveScope, fetchBootstrap } from '../lib/endpoints';
import { ApiError, isAccessRestricted, isTermsOfUseRequired } from '../lib/apiClient';
import type { BootstrapPayload, PromptOption } from '../lib/types';

/**
 * Orders concurrent refreshes so a slower earlier one cannot land after a newer one.
 *
 * Two saves in quick succession issue two refetches, and nothing guarantees the
 * responses arrive in the order the requests left. Without this the interface can settle
 * on the payload from before the second save.
 */
let refreshSequence = 0;

/**
 * Bumped whenever `refreshScope` starts or commits.
 *
 * A workspace switch confirms the new active group with a scope-only read. A full bootstrap
 * read that left before that one -- a tab refocus, say -- may have been built before the
 * switch was saved, so when it lands it must not put the previous group back. Its scope
 * fields are dropped in favour of the ones already in the store; everything else applies.
 */
let scopeSequence = 0;

/** Install a full payload, keeping the newer active scope if one arrived after it left. */
function withCurrentScope(
    data: BootstrapPayload,
    startedAtScope: number,
    current: BootstrapPayload | null,
): BootstrapPayload {
    if (startedAtScope === scopeSequence || !current?.scope || !data?.scope
        || current.user?.id !== data.user?.id) {
        return data;
    }
    return {
        ...data,
        scope: {
            ...data.scope,
            active_group_id: current.scope.active_group_id,
            active_group_name: current.scope.active_group_name,
            active_public_workspace_id: current.scope.active_public_workspace_id,
        },
    };
}

/**
 * When a bootstrap read last started, and how many are in flight.
 *
 * Focus and visibility changes ask for a refresh, and switching windows -- to a Microsoft 365
 * sign-in popup and back, say -- fires them in bursts. The payload takes seconds to build, so
 * `refreshWhenStale` skips a refresh while one is running or one started moments ago.
 */
let lastBootstrapStartedAt = 0;
let bootstrapReadsInFlight = 0;

/** Note that a bootstrap read is starting; call the returned function once it settles. */
function startBootstrapRead(): () => void {
    lastBootstrapStartedAt = Date.now();
    bootstrapReadsInFlight += 1;
    return () => {
        bootstrapReadsInFlight -= 1;
    };
}

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
     * `refresh`, unless a read is already running or one started within `minIntervalMs`.
     * For focus and visibility changes, which arrive in bursts; a save should call `refresh`.
     */
    refreshWhenStale: (minIntervalMs: number) => Promise<void>;
    /** An identity-bound selection must not install a response from a different sign-in. */
    refreshRequired: (expectedViewerId?: string) => Promise<BootstrapPayload>;
    /**
     * Re-read only the active group and public workspace, and patch them in place.
     *
     * Switching group workspaces changes nothing else in the payload, and the full read
     * takes seconds to build. Holds the same identity guard as `refreshRequired`, and
     * throws if a newer scope read started while this one was running.
     */
    refreshScope: (expectedViewerId: string) => Promise<BootstrapPayload>;
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

export const useBootstrapStore = create<BootstrapState>((set, get) => ({
    data: null,
    loading: true,
    error: null,
    authExpired: false,

    load: async () => {
        set({ loading: true, error: null, authExpired: false });
        const settle = startBootstrapRead();
        const startedAtScope = scopeSequence;
        try {
            const data = await fetchBootstrap();
            set({ data: withCurrentScope(data, startedAtScope, get().data), loading: false });
        } catch (error) {
            // The terms gate or the access gate refused the call and apiClient is already
            // navigating to the page that explains it. Staying on the boot screen avoids
            // flashing a misleading "session expired" panel during that navigation.
            if (
                error instanceof ApiError &&
                (isTermsOfUseRequired(error.status, error.payload) ||
                    isAccessRestricted(error.status, error.payload))
            ) {
                return;
            }
            const isAuthError = error instanceof ApiError && error.isAuthError;
            set({
                loading: false,
                authExpired: isAuthError,
                error:
                    error instanceof Error
                        ? error.message
                        : 'Failed to load the application.',
            });
        } finally {
            settle();
        }
    },

    refresh: async () => {
        const sequence = ++refreshSequence;
        const settle = startBootstrapRead();
        const startedAtScope = scopeSequence;
        try {
            const data = await fetchBootstrap();
            if (sequence === refreshSequence) {
                set({ data: withCurrentScope(data, startedAtScope, get().data) });
            }
        } catch {
            // Advisory on purpose, and the reason this cannot be `load()`. App.tsx
            // replaces the whole interface with the boot screen while `loading` is set
            // and with the boot error when `error` is, so driving either from here would
            // tear down the page being worked on -- unsaved edits included -- over a
            // refetch the reader never asked for. The caller's own write already
            // succeeded, so a briefly stale shell is cosmetic and the next load fixes it.
        } finally {
            settle();
        }
    },

    refreshWhenStale: async (minIntervalMs) => {
        if (bootstrapReadsInFlight > 0 || Date.now() - lastBootstrapStartedAt < minIntervalMs) {
            return;
        }
        await get().refresh();
    },

    refreshRequired: async (expectedViewerId) => {
        const sequence = ++refreshSequence;
        const settle = startBootstrapRead();
        const startedAtScope = scopeSequence;
        let data: BootstrapPayload;
        try {
            data = await fetchBootstrap();
        } finally {
            settle();
        }
        if (sequence !== refreshSequence) {
            throw new Error('Application availability changed during refresh. Try again.');
        }
        if (expectedViewerId && (get().authExpired || get().data?.user?.id !== expectedViewerId
            || data?.user?.id !== expectedViewerId)) {
            throw new Error('Your sign-in changed during refresh. Reload the workspace.');
        }
        data = withCurrentScope(data, startedAtScope, get().data);
        set({ data });
        return data;
    },

    refreshScope: async (expectedViewerId) => {
        const previous = get().data;
        if (get().authExpired || previous?.user?.id !== expectedViewerId) {
            throw new Error('Your sign-in changed during refresh. Reload the workspace.');
        }
        const sequence = ++scopeSequence;
        const result = await fetchActiveScope();
        if (sequence !== scopeSequence) {
            throw new Error('The active workspace changed during refresh. Try again.');
        }
        const current = get().data;
        if (!current || get().authExpired || current.user?.id !== expectedViewerId
            || result?.user?.id !== expectedViewerId) {
            throw new Error('Your sign-in changed during refresh. Reload the workspace.');
        }
        const scope = result?.scope;
        if (!scope || typeof scope !== 'object'
            || ![scope.active_group_id, scope.active_public_workspace_id].every(
                (id) => id === null || (typeof id === 'string' && id.trim().length > 0),
            )
            || !(scope.active_group_name === null || typeof scope.active_group_name === 'string')) {
            throw new Error('The active workspace could not be read.');
        }
        if ((['active_group_id', 'active_public_workspace_id'] as const).some(
            (key) => current.scope?.[key] !== previous.scope?.[key]
                && current.scope?.[key] !== scope[key],
        )) {
            throw new Error('The active workspace changed during refresh. Try again.');
        }
        const data: BootstrapPayload = {
            ...current,
            scope: {
                ...current.scope,
                active_group_id: scope.active_group_id,
                active_group_name: scope.active_group_name,
                active_public_workspace_id: scope.active_public_workspace_id,
            },
        };
        // A full read may have started while this scope read was pending.
        ++scopeSequence;
        set({ data });
        return data;
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
