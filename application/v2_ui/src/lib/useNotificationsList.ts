// useNotificationsList.ts
// The list behind the Notifications page: one page of notifications for one view, read from the
// server each time the view changes.
//
// This is deliberately not the bell's notification store. That store keeps one list that only
// grows -- "Load more" appends, and a dismissal or a new notice is reconciled against the pages
// already shown -- which suits a panel and is wrong for numbered pages that are filtered and
// searched by the server. Here every view is simply asked for, and an answer is kept with the
// view it was for, so a slow answer to an earlier view can never be shown under a later one.
//
// The bell's count stays the store's business: when it reports a rise, something new has
// arrived, and the page reads its view again.

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchNotificationPage, type AppNotification } from './notifications';
import {
    notificationsScopeKey,
    notificationsViewKey,
    type NotificationsPageSize,
    type NotificationsView,
} from './notificationsPage';
import { subscribeNotificationCount } from '../stores/notificationStore';

/** A view with the size to list settled; the page waits for the saved preference to settle it. */
export type NotificationsListView = NotificationsView & { perPage: NotificationsPageSize };

export interface NotificationsListResult {
    /** The view this answer was for, as `notificationsViewKey` writes it. */
    key: string;
    /** What that view lists apart from its page, as `notificationsScopeKey` writes it. */
    scope: string;
    items: AppNotification[];
    /** Every notification the view's filters leave, on all pages. */
    total: number;
    perPage: number;
}

export interface NotificationsList {
    /** The latest answer. It may be for an earlier view: compare its `key` with the view's. */
    result: NotificationsListResult | null;
    loading: boolean;
    /** Why the latest read failed, or null. */
    error: string | null;
    /**
     * Read the current view again. Resolves once an answer, or a failure, has been dealt with: with
     * the answer, which is the very object `result` holds, or null for a read that failed.
     */
    reload: () => Promise<NotificationsListResult | null>;
}

const READ_FAILED = 'Your notifications could not be loaded. Try again.';

/** Read the view, or nothing while it is null. A change of view cancels the read before it. */
export function useNotificationsList(view: NotificationsListView | null): NotificationsList {
    const [result, setResult] = useState<NotificationsListResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
    const [reloadToken, setReloadToken] = useState(0);
    const viewRef = useRef(view);
    viewRef.current = view;
    const requestedRef = useRef(0);
    const waitersRef = useRef<{ token: number; resolve: (answer: NotificationsListResult | null) => void }[]>([]);
    const key = view ? notificationsViewKey(view) : null;

    const reload = useCallback(() => {
        requestedRef.current += 1;
        const token = requestedRef.current;
        return new Promise<NotificationsListResult | null>((resolve) => {
            waitersRef.current.push({ token, resolve });
            setReloadToken(token);
        });
    }, []);

    useEffect(() => {
        const current = viewRef.current;
        if (!current || !key) {
            return undefined;
        }
        const controller = new AbortController();
        // Everything asked for up to now is answered by this read, which is at least as new.
        const token = requestedRef.current;
        const settle = (answer: NotificationsListResult | null) => {
            const answered = waitersRef.current.filter((waiter) => waiter.token <= token);
            waitersRef.current = waitersRef.current.filter((waiter) => waiter.token > token);
            for (const waiter of answered) {
                waiter.resolve(answer);
            }
        };
        setLoading(true);
        setFailure(null);
        fetchNotificationPage(current.page, controller.signal, {
            status: current.status,
            query: current.query,
            perPage: current.perPage,
        })
            .then((page) => {
                if (controller.signal.aborted) {
                    return;
                }
                const answer: NotificationsListResult = {
                    key,
                    scope: notificationsScopeKey(current),
                    items: page.notifications,
                    total: page.total,
                    perPage: page.perPage,
                };
                setResult(answer);
                setLoading(false);
                settle(answer);
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                setFailure({ key, message: cause instanceof Error && cause.message ? cause.message : READ_FAILED });
                setLoading(false);
                settle(null);
            });
        return () => controller.abort();
    }, [key, reloadToken]);

    // A notice that arrives while the page is open is listed rather than only counted.
    useEffect(
        () =>
            subscribeNotificationCount((change) => {
                if (change.rose) {
                    void reload();
                }
            }),
        [reload],
    );

    // A failure belongs to the view it happened for: it is not shown under another one.
    return { result, loading, error: failure && failure.key === key ? failure.message : null, reload };
}
