// useWorkflowAlertRuntime.ts
// Feeds the workflow-alert notice: when to ask the server for alerts, and when the page is in
// a state to show one.
//
// It has no timer of its own for the server. The bell's poller (notificationStore.ts) already
// reads the unread count, and this listens to what it reports. The alerts route is read only
// when that count says something may have changed:
//
// - the first count of the visit, and every read when the reader comes back to the tab;
// - the count rising, which is a new notice of some kind;
// - every poll while the count is at the cap, where a new alert cannot move it, with a safety
//   read at most every five minutes otherwise;
// - the count falling when this tab did not cause it, so an alert read in another tab or on
//   another device leaves the notice here too.
//
// Nothing is read while the count is zero: there is nothing unread to pop up.
//
// Whether the notice may show is checked here too, and handed to the store as `suspended`.
// It waits while the tab is hidden, while the mobile navigation is open, and while a dialog is
// open -- any rendered, visible `role="dialog"`, `role="alertdialog"` or open `<dialog>` that
// is not the alert card itself, which includes the bell's own panel.

import { useEffect } from 'react';
import { NOTIFICATION_COUNT_CAP } from './notifications';
import { fetchWorkflowAlerts, workflowAlertEntryIds } from './workflowAlertNotices';
import { lastWorkflowAlertActionAt } from './workflowAlertActions';
import {
    subscribeNotificationCount,
    useNotificationStore,
    type NotificationCountChange,
} from '../stores/notificationStore';
import { useUiStore } from '../stores/uiStore';
import { WORKFLOW_ALERT_UI_ATTRIBUTE, useWorkflowAlertStore } from '../stores/workflowAlertStore';

const SAFETY_FETCH_MS = 5 * 60_000;
/** A fall this soon after the card changed an alert is the card's own doing. */
const OWN_ACTION_GRACE_MS = 3_000;
/** Reads for the reader's return closer together than this are one read. */
const RETURN_FETCH_GAP_MS = 2_000;
/** How long alerts that waited while the tab was hidden hold back for a fresh read. */
const RETURN_HOLD_MS = 3_000;
/** How often a waiting alert checks whether the page is free to show it. */
const GATE_INTERVAL_MS = 700;

const DIALOG_SELECTOR = '[role="dialog"], [role="alertdialog"], dialog[open]';

let feedPaused = false;

/**
 * Stop reading alerts from the server, so something else can feed the store. Only the alert
 * lab does, to show its samples without real alerts replacing them.
 */
export function setWorkflowAlertFeedPaused(paused: boolean): void {
    feedPaused = paused;
}

/** On screen, not merely in the document: a closed dialog kept mounted must not hold alerts back. */
function isShown(element: Element): boolean {
    if (typeof element.checkVisibility === 'function' && !element.checkVisibility({ visibilityProperty: true })) {
        return false;
    }
    if (element.getClientRects().length === 0) {
        return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0
        && rect.bottom > 0 && rect.right > 0
        && rect.top < window.innerHeight && rect.left < window.innerWidth;
}

function dialogOpen(): boolean {
    const alertUi = `[${WORKFLOW_ALERT_UI_ATTRIBUTE}]`;
    for (const element of document.querySelectorAll(DIALOG_SELECTOR)) {
        if (element.closest(alertUi) || element.querySelector(alertUi)) {
            continue;
        }
        if (isShown(element)) {
            return true;
        }
    }
    return false;
}

/** Whether the page is in a state where an alert must wait. */
export function workflowAlertsBlocked(): boolean {
    if (typeof document === 'undefined') {
        return true;
    }
    return document.visibilityState !== 'visible'
        || useUiStore.getState().mobileNavOpen
        || dialogOpen();
}

export function useWorkflowAlertRuntime(ready: boolean): void {
    useEffect(() => {
        if (!ready) {
            return undefined;
        }
        const store = useWorkflowAlertStore;
        let disposed = false;
        let inFlight: AbortController | null = null;
        let again = false;
        let lastFetchAt = 0;
        let holdUntil = 0;
        // Bumped when a hold starts, so only a read that leaves after it can lift it.
        let holdGeneration = 0;
        let gateTimer: ReturnType<typeof setInterval> | null = null;
        let gateQueued = false;

        const pending = (): boolean => {
            const state = store.getState();
            return state.queue.length > 0 || state.entries.length > 0;
        };

        const updateGate = (): void => {
            if (disposed) {
                return;
            }
            store.getState().setSuspended(workflowAlertsBlocked() || Date.now() < holdUntil);
            if (pending()) {
                gateTimer ??= setInterval(updateGate, GATE_INTERVAL_MS);
            } else if (gateTimer !== null) {
                clearInterval(gateTimer);
                gateTimer = null;
            }
        };

        // Deferred, so the gate is never updated from inside another store's update.
        const queueGate = (): void => {
            if (gateQueued) {
                return;
            }
            gateQueued = true;
            queueMicrotask(() => {
                gateQueued = false;
                updateGate();
            });
        };

        /**
         * Read the alerts. A read asked for while one is on its way runs once that one lands,
         * because it may have left before the change it is asked about. A read for the
         * reader's return is not repeated when one has just been made.
         */
        const fetchNow = (kind: 'change' | 'return' = 'change'): void => {
            if (disposed || feedPaused) {
                return;
            }
            if (kind === 'return' && (inFlight || Date.now() - lastFetchAt < RETURN_FETCH_GAP_MS)) {
                return;
            }
            if (inFlight) {
                again = true;
                return;
            }
            const controller = new AbortController();
            const generation = holdGeneration;
            inFlight = controller;
            lastFetchAt = Date.now();
            void fetchWorkflowAlerts(controller.signal)
                .then(({ alerts, complete }) => {
                    if (disposed || feedPaused || controller.signal.aborted) {
                        return;
                    }
                    const state = store.getState();
                    // The gate is only watched while something waits, so a dialog opened
                    // while nothing did is noticed here, before these alerts can be shown.
                    // It only closes here: opening it is left until the alerts waiting have
                    // been replaced, so one read elsewhere is not shown on its way out.
                    if (!state.suspended && workflowAlertsBlocked()) {
                        state.setSuspended(true);
                    }
                    state.receiveAlerts(alerts, { complete });
                })
                .catch(() => {
                    // The alerts already known stay; the bell still counts every one of them.
                })
                .finally(() => {
                    if (inFlight === controller) {
                        inFlight = null;
                    }
                    // A read that left before the reader came back cannot say what changed
                    // while they were away, so it does not lift the hold.
                    if (generation === holdGeneration) {
                        holdUntil = 0;
                    }
                    queueGate();
                    if (again && !disposed) {
                        again = false;
                        fetchNow();
                    }
                });
        };

        const onCount = (change: NotificationCountChange): void => {
            if (feedPaused) {
                return;
            }
            if (change.count <= 0) {
                again = false;
                store.getState().clearAll();
                return;
            }
            if (change.reason === 'initial' || change.reason === 'focus' || change.reason === 'visibility') {
                fetchNow('return');
                return;
            }
            const now = Date.now();
            const fell = change.previousCount !== null && change.count < change.previousCount;
            if (change.rose
                || (change.reason === 'poll' && change.count >= NOTIFICATION_COUNT_CAP)
                || (change.reason === 'poll' && now - lastFetchAt >= SAFETY_FETCH_MS)
                || (fell && pending() && now - lastWorkflowAlertActionAt() > OWN_ACTION_GRACE_MS)) {
                fetchNow();
            }
        };

        const onVisibilityChange = (): void => {
            if (document.visibilityState === 'visible' && store.getState().queue.length > 0) {
                // What waited while the tab was hidden may have been read elsewhere since. It
                // waits for a read that leaves now -- not one skipped because another left a
                // moment ago, nor one already on its way.
                holdGeneration += 1;
                holdUntil = Date.now() + RETURN_HOLD_MS;
                fetchNow();
            }
            updateGate();
        };

        // The bell's store is where this tab reads and dismisses notices. An alert handled
        // there is done with here.
        const unsubscribeBell = useNotificationStore.subscribe((state, previous) => {
            if (state.items === previous.items) {
                return;
            }
            const alerts = store.getState();
            const tracked = new Set([
                ...alerts.queue.map((alert) => alert.id),
                ...alerts.entries.flatMap(workflowAlertEntryIds),
            ]);
            if (!tracked.size) {
                return;
            }
            const items = new Map(state.items.map((item) => [item.id, item]));
            const handled: string[] = [];
            for (const id of tracked) {
                const item = items.get(id);
                if (item?.is_read) {
                    handled.push(id);
                } else if (!item && state.pendingIds[id] && previous.items.some((candidate) => candidate.id === id)) {
                    handled.push(id);
                }
            }
            if (handled.length) {
                store.getState().removeAlerts(handled);
            }
        });

        const unsubscribeAlerts = store.subscribe((state, previous) => {
            if (state.queue !== previous.queue || state.entries !== previous.entries) {
                queueGate();
            }
        });
        const unsubscribeUi = useUiStore.subscribe((state, previous) => {
            if (state.mobileNavOpen !== previous.mobileNavOpen) {
                queueGate();
            }
        });
        const unsubscribeCount = subscribeNotificationCount(onCount);

        // Dialogs are portaled into the body, so one opening or closing shows up here at once
        // rather than at the next check.
        const observer = new MutationObserver(() => {
            if (pending()) {
                queueGate();
            }
        });
        observer.observe(document.body, { childList: true });
        document.addEventListener('visibilitychange', onVisibilityChange);

        // The count may already have been read before this started listening.
        if ((useNotificationStore.getState().count ?? 0) > 0) {
            fetchNow();
        }
        updateGate();

        return () => {
            disposed = true;
            inFlight?.abort();
            inFlight = null;
            if (gateTimer !== null) {
                clearInterval(gateTimer);
            }
            observer.disconnect();
            document.removeEventListener('visibilitychange', onVisibilityChange);
            unsubscribeBell();
            unsubscribeAlerts();
            unsubscribeUi();
            unsubscribeCount();
            store.getState().setSuspended(true);
        };
    }, [ready]);
}
