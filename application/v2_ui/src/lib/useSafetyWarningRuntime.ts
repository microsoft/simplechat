// useSafetyWarningRuntime.ts
// Reads the safety warnings waiting for the signed-in user's acknowledgment, for the dialog in
// SafetyWarningDialog.tsx.
//
// Bootstrap carries how many there are, and the warnings themselves are read only when that
// count is above zero, so a user with nothing to acknowledge costs no extra request. App.tsx
// reads bootstrap again whenever the tab comes back to the front, so the count -- and with it
// this read -- follows a warning sent while the tab was away, or one acknowledged in another
// tab, which the server then no longer counts.

import { useEffect } from 'react';
import { fetchPendingSafetyWarnings } from './safetyWarnings';
import { useSafetyWarningStore } from '../stores/safetyWarningStore';

/**
 * @param pending Warnings bootstrap says are waiting, or null before a session has loaded.
 * @param revision The bootstrap payload, so each fresh read of it is followed even when the
 *   count is unchanged.
 */
export function useSafetyWarningRuntime(pending: number | null, revision: unknown): void {
    useEffect(() => {
        if (pending === null) {
            return undefined;
        }
        if (pending <= 0) {
            useSafetyWarningStore.getState().receive([]);
            return undefined;
        }
        const controller = new AbortController();
        void fetchPendingSafetyWarnings(controller.signal)
            .then((warnings) => {
                if (!controller.signal.aborted) {
                    useSafetyWarningStore.getState().receive(warnings);
                }
            })
            .catch(() => {
                // What is already known stays; the next bootstrap read tries again.
            });
        return () => controller.abort();
    }, [pending, revision]);
}
