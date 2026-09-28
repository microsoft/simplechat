// notificationStore.ts
// The unread count behind the V2 bell, the list behind its panel, and the actions on both.
//
// The count is polled rather than pushed: there is no event stream for personal notices
// (the collaboration stream serves shared chats only). The poller is written to be cheap and
// to stay out of the way:
//
// - It reads the count on start, whenever the window regains focus, and whenever the tab
//   becomes visible, because those are the moments someone is about to look at the bell.
// - While the tab is visible it repeats on a backing-off interval: 30 seconds, doubling each
//   time nothing changed, up to five minutes. A change, or anything the user does to their
//   notifications, brings it back to 30 seconds. Each wait is jittered so many open tabs do
//   not settle into asking in step.
// - While the tab is hidden it does not poll at all. Hidden tabs have their timers throttled
//   anyway (roadmap gotcha 44), and nobody is looking at the bell; the visibility read on
//   return brings it up to date in one request.
// - It stops for good on a signed-out answer -- a 401, a 403, or the sign-in page served in
//   place of JSON -- rather than asking a page that will never answer, every 30 seconds,
//   until the tab is closed.
//
// Other features can listen for changes with `subscribeNotificationCount`. Track N2's
// workflow-alert pop-ups are the intended subscriber: they react to the count rising, and
// re-check their own alerts when the reader comes back to the tab.

import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import {
    NOTIFICATION_COUNT_CAP,
    dismissNotification as dismissNotificationRequest,
    fetchNotificationCount,
    fetchNotificationPage,
    markAllNotificationsRead as markAllNotificationsReadRequest,
    markNotificationRead as markNotificationReadRequest,
    type AppNotification,
} from '../lib/notifications';
import { toast } from './toastStore';

export type NotificationCountReason = 'initial' | 'poll' | 'focus' | 'visibility' | 'action';

export interface NotificationCountChange {
    count: number;
    /** Null for the first read of the visit. */
    previousCount: number | null;
    changed: boolean;
    /** True only when an earlier read exists and this one is higher. */
    rose: boolean;
    reason: NotificationCountReason;
}

type NotificationCountListener = (change: NotificationCountChange) => void;

export const NOTIFICATION_POLL_BASE_MS = 30_000;
export const NOTIFICATION_POLL_MAX_MS = 5 * 60_000;
/** Focus and visibility events arrive in pairs on return; one read answers both. */
const RETURN_READ_GAP_MS = 2_000;

interface NotificationState {
    /** Null until the first successful read. */
    count: number | null;
    /** Set when polling stopped because the session can no longer be read. */
    halted: boolean;
    items: AppNotification[];
    page: number;
    hasMore: boolean;
    listLoading: boolean;
    listLoaded: boolean;
    listError: string | null;
    /** Rows with a read or dismiss request in flight, so their buttons can wait for it. */
    pendingIds: Record<string, true>;
    markingAll: boolean;

    /** Load the first page again, or the next one after the pages already loaded. */
    loadList: (options?: { append?: boolean }) => Promise<void>;
    markRead: (notificationId: string) => Promise<boolean>;
    dismiss: (notificationId: string) => Promise<boolean>;
    markAllRead: () => Promise<boolean>;
}

let running = false;
let timer: ReturnType<typeof setTimeout> | null = null;
let intervalMs = NOTIFICATION_POLL_BASE_MS;
let inFlight: Promise<void> | null = null;
let queuedReason: NotificationCountReason | null = null;
let lastReadStartedAt = 0;
let countWrites = 0;
let listToken = 0;
const listeners = new Set<NotificationCountListener>();

function isVisible(): boolean {
    return typeof document === 'undefined' || document.visibilityState === 'visible';
}

function clearTimer(): void {
    if (timer !== null) {
        clearTimeout(timer);
        timer = null;
    }
}

function schedule(): void {
    clearTimer();
    if (!running || useNotificationStore.getState().halted || !isVisible()) {
        return;
    }
    // Plus or minus ten percent.
    const wait = Math.round(intervalMs * (0.9 + Math.random() * 0.2));
    timer = setTimeout(() => {
        timer = null;
        void readCount('poll');
    }, wait);
}

function halt(): void {
    clearTimer();
    queuedReason = null;
    useNotificationStore.setState({ halted: true });
}

function emit(change: NotificationCountChange): void {
    for (const listener of [...listeners]) {
        try {
            listener(change);
        } catch (error) {
            console.warn('A notification count listener failed.', error);
        }
    }
}

/** Write the count and say so. Every write is counted, so a rollback can tell it was overtaken. */
function writeCount(count: number, reason: NotificationCountReason): void {
    const previousCount = useNotificationStore.getState().count;
    countWrites += 1;
    useNotificationStore.setState({ count });
    emit({
        count,
        previousCount,
        changed: previousCount !== count,
        rose: previousCount !== null && count > previousCount,
        reason,
    });
}

function readCount(reason: NotificationCountReason): Promise<void> {
    if (!running || useNotificationStore.getState().halted) {
        return Promise.resolve();
    }
    if (inFlight) {
        // A read is already on its way. Asking again straight after it lands is only worth it
        // when something may have changed since it left, which is what an action means.
        if (reason === 'action') {
            queuedReason = 'action';
        }
        return inFlight;
    }

    clearTimer();
    lastReadStartedAt = Date.now();
    inFlight = (async () => {
        try {
            const count = await fetchNotificationCount();
            if (!running) {
                return;
            }
            if (count === null) {
                halt();
                return;
            }
            const previous = useNotificationStore.getState().count;
            const userPresent = reason !== 'poll';
            intervalMs = previous !== count || userPresent
                ? NOTIFICATION_POLL_BASE_MS
                : Math.min(intervalMs * 2, NOTIFICATION_POLL_MAX_MS);
            writeCount(count, reason);
        } catch (error) {
            if (!running) {
                return;
            }
            if (error instanceof ApiError && error.isAuthError) {
                halt();
                return;
            }
            // A failed read is not a signed-out one. Try again later, and less often.
            intervalMs = Math.min(intervalMs * 2, NOTIFICATION_POLL_MAX_MS);
        } finally {
            inFlight = null;
        }
        const next = queuedReason;
        queuedReason = null;
        if (next && running) {
            await readCount(next);
            return;
        }
        schedule();
    })();
    return inFlight;
}

function onFocus(): void {
    if (Date.now() - lastReadStartedAt < RETURN_READ_GAP_MS) {
        return;
    }
    void readCount('focus');
}

function onVisibilityChange(): void {
    if (!isVisible()) {
        // Nothing is looking at the bell. The read on return catches up in one request.
        clearTimer();
        return;
    }
    if (Date.now() - lastReadStartedAt < RETURN_READ_GAP_MS) {
        schedule();
        return;
    }
    void readCount('visibility');
}

/**
 * Start polling. Idempotent, so React's development double-run of an effect costs nothing:
 * a stop followed at once by a start reuses the read already on its way.
 */
export function startNotificationPolling(): void {
    if (running) {
        return;
    }
    running = true;
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibilityChange);
    if (inFlight) {
        return;
    }
    void readCount(useNotificationStore.getState().count === null ? 'initial' : 'poll');
}

export function stopNotificationPolling(): void {
    if (!running) {
        return;
    }
    running = false;
    clearTimer();
    queuedReason = null;
    window.removeEventListener('focus', onFocus);
    document.removeEventListener('visibilitychange', onVisibilityChange);
}

/**
 * Read the count now, because something probably changed it -- a reply that just landed, or
 * an action taken elsewhere. Does nothing until polling has started.
 */
export function refreshNotificationCount(reason: NotificationCountReason = 'action'): Promise<void> {
    return readCount(reason);
}

/** Hear about every count read. Returns the function that stops listening. */
export function subscribeNotificationCount(listener: NotificationCountListener): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** The count after one unread notice stops being unread. At the cap it is unknown, so it stays. */
function decrement(count: number | null): number | null {
    if (count === null || count >= NOTIFICATION_COUNT_CAP) {
        return count;
    }
    return Math.max(0, count - 1);
}

function errorMessage(error: unknown, fallback: string): string {
    return error instanceof Error && error.message ? error.message : fallback;
}

function withPending(pendingIds: Record<string, true>, id: string, pending: boolean): Record<string, true> {
    const next = { ...pendingIds };
    if (pending) {
        next[id] = true;
    } else {
        delete next[id];
    }
    return next;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
    count: null,
    halted: false,
    items: [],
    page: 0,
    hasMore: false,
    listLoading: false,
    listLoaded: false,
    listError: null,
    pendingIds: {},
    markingAll: false,

    loadList: async ({ append = false } = {}) => {
        const token = ++listToken;
        const page = append ? get().page + 1 : 1;
        set({ listLoading: true, listError: null });
        try {
            const result = await fetchNotificationPage(page);
            if (token !== listToken) {
                return;
            }
            set((state) => {
                // Pages are cut by position, so a notice dismissed since the last page can shift
                // one that was already loaded onto the next. Merged by id, it is not shown twice.
                const seen = new Set(append ? state.items.map((item) => item.id) : []);
                const fresh = result.notifications.filter((item) => !seen.has(item.id));
                return {
                    items: append ? [...state.items, ...fresh] : fresh,
                    page: result.page,
                    hasMore: result.hasMore,
                    listLoading: false,
                    listLoaded: true,
                };
            });
        } catch (error) {
            if (token !== listToken) {
                return;
            }
            set({
                listLoading: false,
                listError: errorMessage(error, 'Your notifications could not be loaded. Try again.'),
            });
        }
    },

    markRead: async (notificationId) => {
        const item = get().items.find((candidate) => candidate.id === notificationId);
        if (!item || get().pendingIds[notificationId]) {
            return false;
        }
        if (item.is_read) {
            return true;
        }
        const countBefore = get().count;
        set((state) => ({
            items: state.items.map((candidate) =>
                candidate.id === notificationId ? { ...candidate, is_read: true } : candidate,
            ),
            count: decrement(state.count),
            pendingIds: withPending(state.pendingIds, notificationId, true),
        }));
        const writesAtChange = countWrites;
        try {
            await markNotificationReadRequest(notificationId);
            set((state) => ({ pendingIds: withPending(state.pendingIds, notificationId, false) }));
            void refreshNotificationCount('action');
            return true;
        } catch (error) {
            set((state) => ({
                items: state.items.map((candidate) =>
                    candidate.id === notificationId ? { ...candidate, is_read: false } : candidate,
                ),
                // Put the count back only if nothing has written a fresher one meanwhile.
                count: countWrites === writesAtChange ? countBefore : state.count,
                pendingIds: withPending(state.pendingIds, notificationId, false),
            }));
            toast.error(errorMessage(error, 'That notification could not be marked as read.'));
            return false;
        }
    },

    dismiss: async (notificationId) => {
        const index = get().items.findIndex((candidate) => candidate.id === notificationId);
        if (index < 0 || get().pendingIds[notificationId]) {
            return false;
        }
        const item = get().items[index];
        const countBefore = get().count;
        set((state) => ({
            items: state.items.filter((candidate) => candidate.id !== notificationId),
            count: item.is_read ? state.count : decrement(state.count),
            pendingIds: withPending(state.pendingIds, notificationId, true),
        }));
        const writesAtChange = countWrites;
        try {
            await dismissNotificationRequest(notificationId);
            set((state) => ({ pendingIds: withPending(state.pendingIds, notificationId, false) }));
            void refreshNotificationCount('action');
            return true;
        } catch (error) {
            set((state) => {
                const items = [...state.items];
                if (!items.some((candidate) => candidate.id === notificationId)) {
                    items.splice(Math.min(index, items.length), 0, item);
                }
                return {
                    items,
                    count: countWrites === writesAtChange ? countBefore : state.count,
                    pendingIds: withPending(state.pendingIds, notificationId, false),
                };
            });
            toast.error(errorMessage(error, 'That notification could not be dismissed.'));
            return false;
        }
    },

    markAllRead: async () => {
        if (get().markingAll) {
            return false;
        }
        const unreadIds = new Set(get().items.filter((item) => !item.is_read).map((item) => item.id));
        const countBefore = get().count;
        set((state) => ({
            items: state.items.map((item) => (item.is_read ? item : { ...item, is_read: true })),
            count: 0,
            markingAll: true,
        }));
        const writesAtChange = countWrites;
        try {
            await markAllNotificationsReadRequest();
            set({ markingAll: false });
            void refreshNotificationCount('action');
            return true;
        } catch (error) {
            set((state) => ({
                items: state.items.map((item) => (unreadIds.has(item.id) ? { ...item, is_read: false } : item)),
                count: countWrites === writesAtChange ? countBefore : state.count,
                markingAll: false,
            }));
            toast.error(errorMessage(error, 'Your notifications could not be marked as read.'));
            return false;
        }
    },
}));
