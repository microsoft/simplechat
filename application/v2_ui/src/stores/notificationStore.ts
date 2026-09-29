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
//
// Reading, marking read and dismissing change what the server will answer, so the panel shows
// each change at once and the server's answers are kept from undoing it:
//
// - A count read is used only when no change was made, finished or still under way since it
//   was sent. An earlier answer may have been counted before the change reached the server;
//   it is dropped, and the count is read again once the change has landed.
// - A list page is laid under the changes it may have missed. A change is kept from the
//   moment it is made until a page has been asked for after it landed, so an answer that
//   left first cannot bring back a dismissed notice or mark a read one unread again.
// - A change the server refused is not undone from a remembered count, which a later change
//   or read may have overtaken. The count is read again instead.

import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import {
    NOTIFICATION_COUNT_CAP,
    NOTIFICATION_PAGE_SIZE,
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
    /** The count the server reported before this one; null for the first read of the visit. */
    previousCount: number | null;
    changed: boolean;
    /** True only when an earlier read exists and the server now reports more. */
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
/** The last count the server reported; never one this tab worked out for itself. */
let lastServerCount: number | null = null;
/** Moves on whenever a change is made here and again when it lands, so older reads can tell. */
let changeEpoch = 0;
/** Changes made here that the server has not answered yet. */
let changesInFlight = 0;
let listToken = 0;
const listeners = new Set<NotificationCountListener>();

/**
 * A change made here that a list page may not show yet.
 *
 * `forced` holds the notices a mark-all-read change showed as read on pages that arrived while
 * it was on its way, so a refusal can show them unread again.
 */
interface LocalChange {
    kind: 'read' | 'dismiss' | 'read-all';
    id: string | null;
    landed: boolean;
    forced: Set<string>;
}

const localChanges = new Set<LocalChange>();
/**
 * Dismissals that may have moved later notices up the list since the last page was asked for.
 *
 * Pages are cut by position among the notices that are left, so each dismissal lifts every
 * later notice by one place, and the first notice not loaded yet can slide back onto a page
 * already read. Counted generously -- a dismissal still on its way, or one that then fails,
 * counts too -- because counting one too many costs only a page read again, whose repeats are
 * dropped by id, while one too few would leave a notice out of the list for good.
 */
let dismissalsSincePage = 0;

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

/** Write a count the server reported, and say so, measured against the one it reported before. */
function writeCount(count: number, reason: NotificationCountReason): void {
    const previousCount = lastServerCount;
    lastServerCount = count;
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
    const epochAtStart = changeEpoch;
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
            if (epochAtStart !== changeEpoch || changesInFlight > 0) {
                // Counted before a change of ours reached the server, or while one still has not.
                // Used, it would put back a notice already read or dismissed here. A change still
                // on its way asks for a fresh read when it lands; otherwise ask now.
                if (changesInFlight === 0) {
                    queuedReason = 'action';
                }
            } else {
                const userPresent = reason !== 'poll';
                intervalMs = lastServerCount !== count || userPresent
                    ? NOTIFICATION_POLL_BASE_MS
                    : Math.min(intervalMs * 2, NOTIFICATION_POLL_MAX_MS);
                writeCount(count, reason);
            }
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

/** Whether a count read is on its way. One queued behind it starts the moment it lands. */
export function isNotificationCountReading(): boolean {
    return inFlight !== null;
}

/**
 * Hear about every count the server reports. Returns the function that stops listening.
 *
 * `previousCount`, `changed` and `rose` compare the count the server just reported with the
 * one it reported before -- never with a count this tab worked out for itself after a read,
 * dismiss or mark-all-read. So a notice read here and then counted by the server is not a
 * fall followed by a rise, and `rose` means the server now holds more unread notices than it
 * last said: something new arrived. Track N2's pop-ups rely on that. A read that was counted
 * before a change of ours reached the server is dropped rather than reported, and the count is
 * read again once the change has landed.
 */
export function subscribeNotificationCount(listener: NotificationCountListener): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** Start a change here: a count read that was sent before it can no longer be trusted. */
function beginChange(change: LocalChange): void {
    changeEpoch += 1;
    changesInFlight += 1;
    localChanges.add(change);
    if (change.kind === 'dismiss') {
        dismissalsSincePage += 1;
    }
}

/**
 * Finish a change the server has answered, and read the count again to see where it left
 * things. A refused change is forgotten, so later pages show the notice as the server has it.
 */
function endChange(change: LocalChange, landed: boolean): void {
    changeEpoch += 1;
    changesInFlight = Math.max(0, changesInFlight - 1);
    if (landed) {
        change.landed = true;
    } else {
        localChanges.delete(change);
    }
    void refreshNotificationCount('action');
}

/**
 * Forget the changes that landed. A page asked for from now on already shows them, and a
 * mark-all-read kept past this point would hide a notice that arrived after it.
 */
function forgetLandedChanges(): void {
    for (const change of localChanges) {
        if (change.landed) {
            localChanges.delete(change);
        }
    }
}

/** Lay the changes made here over a page the server may have answered before they landed. */
function withLocalChanges(notifications: AppNotification[]): AppNotification[] {
    if (localChanges.size === 0) {
        return notifications;
    }
    const dismissed = new Set<string>();
    const read = new Set<string>();
    const readAll: LocalChange[] = [];
    for (const change of localChanges) {
        if (change.kind === 'read-all') {
            readAll.push(change);
        } else if (change.id !== null) {
            (change.kind === 'dismiss' ? dismissed : read).add(change.id);
        }
    }
    const shown: AppNotification[] = [];
    for (const item of notifications) {
        if (dismissed.has(item.id)) {
            continue;
        }
        if (item.is_read) {
            shown.push(item);
        } else if (read.has(item.id)) {
            shown.push({ ...item, is_read: true });
        } else if (readAll.length > 0) {
            for (const change of readAll) {
                if (!change.landed) {
                    change.forced.add(item.id);
                }
            }
            shown.push({ ...item, is_read: true });
        } else {
            shown.push(item);
        }
    }
    return shown;
}

function pendingDismissals(): number {
    let pending = 0;
    for (const change of localChanges) {
        if (change.kind === 'dismiss' && !change.landed) {
            pending += 1;
        }
    }
    return pending;
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
        forgetLandedChanges();
        const lastPage = append ? get().page + 1 : 1;
        // Pages are cut by position among the notices that are left. A notice that arrived
        // since the last page moves the rest down, so the next page repeats one already
        // shown; those are dropped by id. A dismissal moves the rest up instead, so the first
        // notice not loaded yet slides back onto a page already read. Asking for the next page
        // alone would skip it for good, so read back one page for every page's worth of
        // dismissals since the last page was asked for.
        const dismissalsAtStart = dismissalsSincePage;
        const pendingAtStart = pendingDismissals();
        const firstPage = append
            ? Math.max(1, lastPage - Math.ceil(dismissalsAtStart / NOTIFICATION_PAGE_SIZE))
            : 1;
        set({ listLoading: true, listError: null });
        try {
            const pages: number[] = [];
            for (let page = firstPage; page <= lastPage; page += 1) {
                pages.push(page);
            }
            const results = await Promise.all(pages.map((page) => fetchNotificationPage(page)));
            if (token !== listToken) {
                return;
            }
            // Dismissals made while this was on its way, and those still on theirs when it
            // left, may yet move the list again. The rest are shown by the pages just read.
            dismissalsSincePage = dismissalsSincePage - dismissalsAtStart + pendingAtStart;
            const last = results[results.length - 1];
            const shown = results.flatMap((result) => withLocalChanges(result.notifications));
            set((state) => {
                const kept = append ? state.items : [];
                const seen = new Set(kept.map((item) => item.id));
                const fresh: AppNotification[] = [];
                for (const item of shown) {
                    if (!seen.has(item.id)) {
                        seen.add(item.id);
                        fresh.push(item);
                    }
                }
                return {
                    items: [...kept, ...fresh],
                    page: last.page,
                    hasMore: last.hasMore,
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
        const change: LocalChange = { kind: 'read', id: notificationId, landed: false, forced: new Set() };
        beginChange(change);
        set((state) => ({
            items: state.items.map((candidate) =>
                candidate.id === notificationId ? { ...candidate, is_read: true } : candidate,
            ),
            count: decrement(state.count),
            pendingIds: withPending(state.pendingIds, notificationId, true),
        }));
        try {
            await markNotificationReadRequest(notificationId);
            set((state) => ({ pendingIds: withPending(state.pendingIds, notificationId, false) }));
            endChange(change, true);
            return true;
        } catch (error) {
            set((state) => ({
                items: state.items.map((candidate) =>
                    candidate.id === notificationId ? { ...candidate, is_read: false } : candidate,
                ),
                pendingIds: withPending(state.pendingIds, notificationId, false),
            }));
            // The count is read again rather than put back: a later change or read may have
            // moved it since this one was made.
            endChange(change, false);
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
        const change: LocalChange = { kind: 'dismiss', id: notificationId, landed: false, forced: new Set() };
        beginChange(change);
        set((state) => ({
            items: state.items.filter((candidate) => candidate.id !== notificationId),
            count: item.is_read ? state.count : decrement(state.count),
            pendingIds: withPending(state.pendingIds, notificationId, true),
        }));
        try {
            await dismissNotificationRequest(notificationId);
            set((state) => ({ pendingIds: withPending(state.pendingIds, notificationId, false) }));
            endChange(change, true);
            return true;
        } catch (error) {
            set((state) => {
                const items = [...state.items];
                if (!items.some((candidate) => candidate.id === notificationId)) {
                    items.splice(Math.min(index, items.length), 0, item);
                }
                return {
                    items,
                    pendingIds: withPending(state.pendingIds, notificationId, false),
                };
            });
            endChange(change, false);
            toast.error(errorMessage(error, 'That notification could not be dismissed.'));
            return false;
        }
    },

    markAllRead: async () => {
        if (get().markingAll) {
            return false;
        }
        const change: LocalChange = { kind: 'read-all', id: null, landed: false, forced: new Set() };
        for (const item of get().items) {
            if (!item.is_read) {
                change.forced.add(item.id);
            }
        }
        beginChange(change);
        set((state) => ({
            items: state.items.map((item) => (item.is_read ? item : { ...item, is_read: true })),
            count: 0,
            markingAll: true,
        }));
        try {
            await markAllNotificationsReadRequest();
            set({ markingAll: false });
            endChange(change, true);
            return true;
        } catch (error) {
            // Show unread again what this change showed as read, including rows on pages that
            // arrived while it was on its way.
            set((state) => ({
                items: state.items.map((item) => (change.forced.has(item.id) ? { ...item, is_read: false } : item)),
                markingAll: false,
            }));
            endChange(change, false);
            toast.error(errorMessage(error, 'Your notifications could not be marked as read.'));
            return false;
        }
    },
}));
