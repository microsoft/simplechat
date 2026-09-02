// userSettingsStore.ts
// Per-user preferences, loaded once and saved as they change.
//
// Saving is deliberately different from the classic interface, which posts one section at a
// time behind an explicit Save button. Here a change is applied to the store immediately and
// the write is debounced, so a slider being dragged produces one request rather than thirty.
// Pending keys are merged into a single payload because the route merges partial updates
// server-side; sending them separately would race, and the last response would win rather
// than the last change.
//
// A failed save rolls the affected keys back to what the server last confirmed. Leaving a
// control showing a value that was never stored is worse than showing the change being
// undone, because the user has no other way to find out it did not take.

import { create } from 'zustand';
import { api, ApiError } from '../lib/apiClient';
import type { UserSettings, UserSettingsResponse } from '../lib/userSettings';

/** How long to wait for further changes before writing. */
const SAVE_DEBOUNCE_MS = 400;

interface UserSettingsState {
    settings: UserSettings;
    loading: boolean;
    /** Null until the first load succeeds or fails. */
    error: string | null;
    saving: boolean;
    saveError: string | null;
    load: () => Promise<void>;
    /** Apply a change locally and schedule it to be written. */
    update: (partial: UserSettings) => void;
    /** Write any pending changes now, e.g. before navigating away. */
    flush: () => Promise<void>;
}

/**
 * Keys changed since the last successful write.
 *
 * Held outside the store because it is bookkeeping rather than render state; putting it in
 * the store would re-render every subscriber on each keystroke.
 */
let pending: UserSettings = {};

/** The values those keys had before the pending change, for rollback. */
let rollback: UserSettings = {};

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let inFlight: Promise<void> | null = null;

export const useUserSettingsStore = create<UserSettingsState>((set, get) => {
    /** Write whatever is pending. Safe to call when nothing is. */
    const writePending = async (): Promise<void> => {
        if (Object.keys(pending).length === 0) {
            return;
        }

        // Captured before the await: further changes during the request belong to the next
        // write, not this one, and must not be cleared by it.
        const payload = pending;
        const previous = rollback;
        pending = {};
        rollback = {};

        set({ saving: true, saveError: null });
        try {
            await api.post<{ message?: string }>('/api/user/settings', { settings: payload });
            set({ saving: false });
        } catch (error) {
            // Only the keys this request carried are reverted; anything changed since is
            // still pending and should not be disturbed.
            set((state) => ({
                saving: false,
                saveError:
                    error instanceof ApiError
                        ? error.message
                        : 'Your preference could not be saved.',
                settings: { ...state.settings, ...previous },
            }));
        }
    };

    const scheduleWrite = () => {
        if (saveTimer !== null) {
            clearTimeout(saveTimer);
        }
        saveTimer = setTimeout(() => {
            saveTimer = null;
            inFlight = writePending();
        }, SAVE_DEBOUNCE_MS);
    };

    return {
        settings: {},
        loading: true,
        error: null,
        saving: false,
        saveError: null,

        load: async () => {
            set({ loading: true, error: null });
            try {
                const response = await api.get<UserSettingsResponse>('/api/user/settings');
                set({ settings: response?.settings ?? {}, loading: false });
            } catch (error) {
                set({
                    loading: false,
                    error:
                        error instanceof Error
                            ? error.message
                            : 'Failed to load your preferences.',
                });
            }
        },

        update: (partial) => {
            const current = get().settings;

            for (const key of Object.keys(partial)) {
                // Recorded once per key: if a value changes twice before the write lands,
                // the correct rollback target is still the server's last known value.
                if (!(key in rollback)) {
                    rollback[key] = current[key];
                }
            }

            pending = { ...pending, ...partial };
            set({ settings: { ...current, ...partial }, saveError: null });
            scheduleWrite();
        },

        flush: async () => {
            if (saveTimer !== null) {
                clearTimeout(saveTimer);
                saveTimer = null;
                inFlight = writePending();
            }
            await inFlight;
        },
    };
});

/** Read one preference, falling back when it has never been set. */
export function useUserSetting<T>(key: string, fallback: T): T {
    return useUserSettingsStore((state) => {
        const value = state.settings[key];
        return (value === undefined || value === null ? fallback : value) as T;
    });
}
