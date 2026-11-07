// safetyWarningStore.ts
// The safety warnings waiting for the signed-in user's acknowledgment. The runtime that reads
// them (lib/useSafetyWarningRuntime.ts) fills it, and the dialog that shows them
// (components/notifications/SafetyWarningDialog.tsx) acknowledges them, oldest first.
//
// A reviewer can warn about the same violation again, so everything here tells warnings apart
// by safetyWarningKey -- the violation and when the warning was sent -- not by violation alone.

import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import {
    SAFETY_WARNING_REPLACED_CODE,
    acknowledgeSafetyWarning,
    fetchPendingSafetyWarnings,
    safetyWarningKey,
    type SafetyWarning,
} from '../lib/safetyWarnings';

export const SAFETY_WARNING_ACKNOWLEDGE_ERROR = 'Your acknowledgment could not be saved. Try again.';

interface SafetyWarningState {
    /** Waiting for acknowledgment, oldest first. The dialog shows the first. */
    warnings: SafetyWarning[];
    /** The safetyWarningKey of the warning being acknowledged. */
    acknowledgingKey: string | null;
    error: string | null;
    /** Replace the list with the server's. */
    receive: (warnings: SafetyWarning[]) => void;
    /** Acknowledge one warning. Resolves true once it no longer needs acknowledgment. */
    acknowledge: (warning: SafetyWarning) => Promise<boolean>;
    reset: () => void;
}

/**
 * Warnings acknowledged in this tab, by safetyWarningKey. A read that left before the
 * acknowledgment landed still lists them, and must not bring the dialog back for a warning
 * already answered -- but a newer warning on the same violation is a different warning.
 */
const acknowledgedKeys = new Set<string>();

function isReplacedWarning(error: unknown): boolean {
    if (!(error instanceof ApiError) || error.status !== 409) {
        return false;
    }
    const payload = error.payload;
    return Boolean(payload && typeof payload === 'object'
        && (payload as Record<string, unknown>).code === SAFETY_WARNING_REPLACED_CODE);
}

export const useSafetyWarningStore = create<SafetyWarningState>((set, get) => ({
    warnings: [],
    acknowledgingKey: null,
    error: null,

    receive: (warnings) =>
        set((state) => {
            const next = warnings.filter((warning) => !acknowledgedKeys.has(safetyWarningKey(warning)));
            // An error belongs to the warning on screen; a different one starts clean.
            const lead = state.warnings[0];
            const nextLead = next[0];
            const sameLead = Boolean(lead && nextLead && safetyWarningKey(lead) === safetyWarningKey(nextLead));
            return { warnings: next, error: sameLead ? state.error : null };
        }),

    acknowledge: async (warning) => {
        if (get().acknowledgingKey) {
            return false;
        }
        const key = safetyWarningKey(warning);
        set({ acknowledgingKey: key, error: null });
        let replaced = false;
        try {
            await acknowledgeSafetyWarning(warning);
        } catch (error) {
            // 404 means it no longer needs acknowledgment here: it was withdrawn. 409 replaced
            // means a newer warning on the same violation took its place, so that one is read
            // next. Anything else keeps it on screen to try again.
            replaced = isReplacedWarning(error);
            if (!replaced && !(error instanceof ApiError && error.status === 404)) {
                set({ acknowledgingKey: null, error: SAFETY_WARNING_ACKNOWLEDGE_ERROR });
                return false;
            }
        }
        acknowledgedKeys.add(key);
        set((state) => ({
            warnings: state.warnings.filter((item) => safetyWarningKey(item) !== key),
            acknowledgingKey: null,
            error: null,
        }));
        if (replaced) {
            try {
                get().receive(await fetchPendingSafetyWarnings());
            } catch {
                // The next bootstrap read shows the newer warning.
            }
        }
        return true;
    },

    reset: () => {
        acknowledgedKeys.clear();
        set({ warnings: [], acknowledgingKey: null, error: null });
    },
}));