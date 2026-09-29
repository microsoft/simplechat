// workflowAlertActions.ts
// What the alert card does to an alert: mark it read, dismiss it, or follow one of its links.
//
// The bell's store owns reading and dismissing for the notices it has loaded: it updates its
// list and its count at once, and puts both back if the server refuses. An alert the bell has
// not loaded -- its panel loads a page at a time, and only when opened -- is sent straight to
// the same route, and the bell reads its count again afterwards. Either way the two
// interfaces agree, because both read and write the same notification documents.
//
// Links are followed by the bell's own navigation (notificationNavigation.ts), after the
// bell's resolver has checked them, so the card never builds an address of its own.

import { dismissNotification, markNotificationRead } from './notifications';
import type { NotificationTarget } from './notificationLinks';
import { openNotificationTarget, type NotificationNavigationContext } from './notificationNavigation';
import { refreshNotificationCount, useNotificationStore } from '../stores/notificationStore';
import { toast } from '../stores/toastStore';

export interface WorkflowAlertActions {
    /** Resolves to the ids that are now read. */
    markRead: (ids: string[]) => Promise<string[]>;
    /** Resolves to the ids that are now dismissed. */
    dismiss: (ids: string[]) => Promise<string[]>;
    /** Follow a resolved link, or an open action's route. */
    open: (target: NotificationTarget, context: NotificationNavigationContext) => Promise<void>;
}

let lastActionAt = 0;

/**
 * When the card last changed a notice. The bell count falls after each change, and the
 * runtime reads that fall as its own doing rather than as news from another tab.
 */
export function lastWorkflowAlertActionAt(): number {
    return lastActionAt;
}

async function apply(
    ids: string[],
    viaBell: (id: string) => Promise<boolean>,
    direct: (id: string) => Promise<unknown>,
    failure: string,
): Promise<string[]> {
    lastActionAt = Date.now();
    let sentDirectly = false;
    let directFailed = false;
    const results = await Promise.all(ids.map(async (id) => {
        if (useNotificationStore.getState().items.some((item) => item.id === id)) {
            // The bell's store reports its own failures.
            return (await viaBell(id)) ? id : null;
        }
        sentDirectly = true;
        try {
            await direct(id);
            return id;
        } catch {
            directFailed = true;
            return null;
        }
    }));
    lastActionAt = Date.now();
    if (sentDirectly) {
        void refreshNotificationCount('action');
    }
    if (directFailed) {
        toast.error(failure);
    }
    return results.filter((id): id is string => id !== null);
}

export const workflowAlertServerActions: WorkflowAlertActions = {
    markRead: (ids) => apply(
        ids,
        (id) => useNotificationStore.getState().markRead(id),
        markNotificationRead,
        ids.length > 1 ? 'Those alerts could not all be marked as read.' : 'That alert could not be marked as read.',
    ),
    dismiss: (ids) => apply(
        ids,
        (id) => useNotificationStore.getState().dismiss(id),
        dismissNotification,
        ids.length > 1 ? 'Those alerts could not all be dismissed.' : 'That alert could not be dismissed.',
    ),
    open: openNotificationTarget,
};
