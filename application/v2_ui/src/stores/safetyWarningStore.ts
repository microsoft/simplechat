// safetyWarningStore.ts
// The safety warnings waiting for the signed-in user's acknowledgment. The runtime that reads
// them (lib/useSafetyWarningRuntime.ts) fills it, and the dialog that shows them
// (components/notifications/SafetyWarningDialog.tsx) acknowledges them, oldest first.

import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import { acknowledgeSafetyWarning, type SafetyWarning } from '../lib/safetyWarnings';

export const SAFETY_WARNING_ACKNOWLEDGE_ERROR = 'Your acknowledgment could not be saved. Try again.';

interface SafetyWarningState {
    /** Waiting for acknowledgment, oldest first. The dialog shows the first. */
    warnings: SafetyWarning[];
    acknowledgingId: string | null;
    error: string | null;
    /** Replace the list with the server's. */
    receive: (warnings: SafetyWarning[]) => void;
    /** Acknowledge one warning. Resolves true once it no longer needs acknowledgment. */
    acknowledge: (id: string) => Promise<boolean>;
    reset: () => void;
}

/**
 * Warnings acknowledged in this tab. A read that left before the acknowledgment landed still
 * lists them, and must not bring the dialog back for a warning already answered.
 */
const acknowledgedIds = new Set<string>();

export const useSafetyWarningStore = create<SafetyWarningState>((set, get) => ({
    warnings: [],
    acknowledgingId: null,
    error: null,

    receive: (warnings) =>
        set((state) => {
            const next = warnings.filter((warning) => !acknowledgedIds.has(warning.id));
            // An error belongs to the warning on screen; a different one starts clean.
            const sameLead = state.warnings[0]?.id === next[0]?.id;
            return { warnings: next, error: sameLead ? state.error : null };
        }),

    acknowledge: async (id) => {
        if (get().acknowledgingId) {
            return false;
        }
        set({ acknowledgingId: id, error: null });
        try {
            await acknowledgeSafetyWarning(id);
        } catch (error) {
            // 404 means it no longer needs acknowledgment here: it was withdrawn, or answered
            // in another tab. Anything else keeps it on screen to try again.
            if (!(error instanceof ApiError && error.status === 404)) {
                set({ acknowledgingId: null, error: SAFETY_WARNING_ACKNOWLEDGE_ERROR });
                return false;
            }
        }
        acknowledgedIds.add(id);
        set((state) => ({
            warnings: state.warnings.filter((warning) => warning.id !== id),
            acknowledgingId: null,
            error: null,
        }));
        return true;
    },

    reset: () => {
        acknowledgedIds.clear();
        set({ warnings: [], acknowledgingId: null, error: null });
    },
}));
