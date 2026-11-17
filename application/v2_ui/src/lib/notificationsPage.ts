// notificationsPage.ts
// The Notifications page's view of the list -- which notifications, what to search for, which
// page, how many to a page -- as it is kept in the address, and the wording around the results.
//
// The address is the source of truth, so Back, Forward, a bookmark and a link from a notice all
// reopen the same view. Everything here is lenient in what it reads and strict in what it
// writes: a hand-edited or stale address falls back to a value the server accepts instead of
// stranding the reader on a request that would only be refused again, and an address is written
// with only the values that differ from the defaults, so a plain `/notifications` stays plain.
//
// Kept free of store and React imports so it can be tested directly under Node.

export const NOTIFICATION_STATUSES = ['all', 'unread', 'read'] as const;
export type NotificationStatus = (typeof NOTIFICATION_STATUSES)[number];

/** The page sizes GET /api/notifications accepts; it replaces any other size with 20. */
export const NOTIFICATIONS_PAGE_SIZES = [10, 20, 50] as const;
export type NotificationsPageSize = (typeof NOTIFICATIONS_PAGE_SIZES)[number];
export const DEFAULT_NOTIFICATIONS_PAGE_SIZE: NotificationsPageSize = 20;

/** The server uses the first 100 characters of a search (functions_notifications.py). */
export const NOTIFICATIONS_SEARCH_MAX_LENGTH = 100;

/** Far beyond any list 60 days of notifications can make, and short of numbers that misbehave. */
export const NOTIFICATIONS_MAX_PAGE = 10_000;

export interface NotificationsView {
    status: NotificationStatus;
    /** What the title or message must contain, ignoring case. Empty for no search. */
    query: string;
    /** 1-based. */
    page: number;
    /** Null when the address names no size, so the reader's saved preference decides. */
    perPage: NotificationsPageSize | null;
}

export const DEFAULT_NOTIFICATIONS_VIEW: NotificationsView = {
    status: 'all',
    query: '',
    page: 1,
    perPage: null,
};

export function normalizeNotificationsStatus(value: unknown): NotificationStatus {
    const status = typeof value === 'string' ? value.trim().toLowerCase() : '';
    return (NOTIFICATION_STATUSES as readonly string[]).includes(status) ? (status as NotificationStatus) : 'all';
}

/** The search as the server will use it: trimmed, and no longer than it reads. */
export function normalizeNotificationsQuery(value: unknown): string {
    if (typeof value !== 'string') {
        return '';
    }
    // Counted in characters, as the server counts them, not in UTF-16 units.
    return Array.from(value.trim()).slice(0, NOTIFICATIONS_SEARCH_MAX_LENGTH).join('').trim();
}

/** A page size the server offers, or null for anything else, including a number as text. */
export function normalizeNotificationsPageSize(value: unknown): NotificationsPageSize | null {
    const size = typeof value === 'string' && /^\d{1,3}$/.test(value.trim()) ? Number(value) : value;
    return (NOTIFICATIONS_PAGE_SIZES as readonly unknown[]).includes(size) ? (size as NotificationsPageSize) : null;
}

/** Page 1 for anything that is not a whole number from 1, and never beyond the cap. */
export function normalizeNotificationsPage(value: unknown): number {
    const page = typeof value === 'string' && /^\d{1,6}$/.test(value.trim()) ? Number(value) : value;
    if (typeof page !== 'number' || !Number.isInteger(page) || page < 1) {
        return 1;
    }
    return Math.min(page, NOTIFICATIONS_MAX_PAGE);
}

/**
 * The size to list: the one in the address, else the reader's saved preference, else 20.
 *
 * `saved` is whatever the user's settings hold under `notifications_per_page`, which is only
 * ever written by the server's own check but is read defensively all the same.
 */
export function resolveNotificationsPageSize(
    fromAddress: NotificationsPageSize | null,
    saved: unknown,
): NotificationsPageSize {
    return fromAddress ?? normalizeNotificationsPageSize(saved) ?? DEFAULT_NOTIFICATIONS_PAGE_SIZE;
}

/** Read a view from an address's query string. Unknown parameters are ignored. */
export function parseNotificationsView(search: string | URLSearchParams): NotificationsView {
    const params = typeof search === 'string' ? new URLSearchParams(search) : search;
    return {
        status: normalizeNotificationsStatus(params.get('status')),
        query: normalizeNotificationsQuery(params.get('q')),
        page: normalizeNotificationsPage(params.get('page')),
        perPage: normalizeNotificationsPageSize(params.get('per_page')),
    };
}

/** The query parameters for a view: only what differs from the defaults, in a fixed order. */
export function notificationsViewParams(view: NotificationsView): URLSearchParams {
    const params = new URLSearchParams();
    const status = normalizeNotificationsStatus(view.status);
    const query = normalizeNotificationsQuery(view.query);
    const page = normalizeNotificationsPage(view.page);
    const perPage = normalizeNotificationsPageSize(view.perPage);
    if (status !== 'all') {
        params.set('status', status);
    }
    if (query) {
        params.set('q', query);
    }
    if (page > 1) {
        params.set('page', String(page));
    }
    if (perPage !== null) {
        params.set('per_page', String(perPage));
    }
    return params;
}

/** A view as a query string without its leading `?`; empty for the default view. */
export function serializeNotificationsView(view: NotificationsView): string {
    return notificationsViewParams(view).toString();
}

/** The page's route, relative to the router's `/v2` base. */
export const NOTIFICATIONS_PATH = '/notifications';

/**
 * The route for a link that names this page, such as classic's `/notifications`.
 *
 * Only the parameters the page reads survive, and in their canonical form, so a link cannot
 * carry anything else into the route.
 */
export function notificationsPathFor(search: string | URLSearchParams): string {
    const query = serializeNotificationsView(parseNotificationsView(search));
    return query ? `${NOTIFICATIONS_PATH}?${query}` : NOTIFICATIONS_PATH;
}

/** A stable identity for what a list answers, so an answer can be matched to the view it was for. */
export function notificationsViewKey(view: NotificationsView & { perPage: NotificationsPageSize }): string {
    return `${notificationsScopeKey(view)}|${view.page}`;
}

/**
 * What a view lists apart from which page of it: the filter, the search and the page size.
 *
 * Two views with the same scope have the same number of pages, so the pager can stay on screen,
 * with its count, while the page a reader asked for is on its way.
 */
export function notificationsScopeKey(view: NotificationsView & { perPage: NotificationsPageSize }): string {
    return `${view.status}|${view.perPage}|${view.query}`;
}

/** How many pages `total` notifications make, never fewer than one. */
export function notificationsPageCount(total: number, perPage: number): number {
    const count = Math.max(0, Math.trunc(total) || 0);
    const size = Math.max(1, Math.trunc(perPage) || DEFAULT_NOTIFICATIONS_PAGE_SIZE);
    return Math.max(1, Math.ceil(count / size));
}

/** A page number held inside the pages that exist, for a list that has shrunk under the reader. */
export function clampNotificationsPage(page: number, total: number, perPage: number): number {
    const requested = Math.max(1, Math.trunc(page) || 1);
    return Math.min(requested, notificationsPageCount(total, perPage));
}

/** The first and last notification numbers on a page, counting from 1; both 0 for an empty list. */
export function notificationsPageRange(
    page: number,
    perPage: number,
    total: number,
): { from: number; to: number } {
    const count = Math.max(0, Math.trunc(total) || 0);
    if (count === 0) {
        return { from: 0, to: 0 };
    }
    const size = Math.max(1, Math.trunc(perPage) || DEFAULT_NOTIFICATIONS_PAGE_SIZE);
    const current = clampNotificationsPage(page, count, size);
    return { from: (current - 1) * size + 1, to: Math.min(count, current * size) };
}

/**
 * The page numbers to offer, with null standing for a gap.
 *
 * Offers exactly `maxButtons` slots once there are more pages than that, counting each gap as
 * a slot, so the control keeps its width as the window moves and the Next button does not slide
 * out from under the pointer on the click that moved it.
 */
export function notificationsPageItems(page: number, pageCount: number, maxButtons = 7): (number | null)[] {
    const count = Math.max(1, Math.trunc(pageCount) || 1);
    const slots = Math.max(5, Math.trunc(maxButtons) || 7);
    const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, index) => from + index);
    if (count <= slots) {
        return range(1, count);
    }
    const current = Math.min(count, Math.max(1, Math.trunc(page) || 1));
    // One anchor and one gap on the far side leave this many contiguous pages.
    const edge = slots - 2;
    // Two anchors and two gaps leave this many, centred on the current page.
    const middle = slots - 4;
    if (current <= slots - 3) {
        return [...range(1, edge), null, count];
    }
    if (current >= count - middle) {
        return [1, null, ...range(count - edge + 1, count)];
    }
    const before = Math.floor(middle / 2);
    return [1, null, ...range(current - before, current - before + middle - 1), null, count];
}

const STATUS_NOUNS: Record<NotificationStatus, [singular: string, plural: string]> = {
    all: ['notification', 'notifications'],
    unread: ['unread notification', 'unread notifications'],
    read: ['read notification', 'read notifications'],
};

/**
 * One sentence for what the list now shows, read aloud by the page's live region.
 *
 * The search text itself is left out: it can be long, and the reader just typed it.
 */
export function describeNotificationResults(input: {
    total: number;
    page: number;
    perPage: number;
    status: NotificationStatus;
    query: string;
}): string {
    const total = Math.max(0, Math.trunc(input.total) || 0);
    const status = normalizeNotificationsStatus(input.status);
    const searching = normalizeNotificationsQuery(input.query) !== '';
    if (total === 0) {
        if (searching) {
            return 'No notifications match your search.';
        }
        return status === 'all' ? 'No notifications.' : `No ${STATUS_NOUNS[status][1]}.`;
    }
    const { from, to } = notificationsPageRange(input.page, input.perPage, total);
    const nouns = STATUS_NOUNS[status];
    const position = from === to ? `Showing ${from}` : `Showing ${from}\u2013${to}`;
    return `${position} of ${total} ${total === 1 ? nouns[0] : nouns[1]}${searching ? ' matching your search' : ''}.`;
}

export interface NotificationsEmptyCopy {
    title: string;
    description: string;
    /** Whether clearing the search would change what is shown. */
    clearable: boolean;
}

/** The empty state for a list with nothing in it, which depends on why it is empty. */
export function describeEmptyNotifications(view: Pick<NotificationsView, 'status' | 'query'>): NotificationsEmptyCopy {
    if (normalizeNotificationsQuery(view.query) !== '') {
        return {
            title: 'No notifications match your search',
            description: 'Try different words, or clear the search to see everything again.',
            clearable: true,
        };
    }
    if (view.status === 'unread') {
        return {
            title: 'No unread notifications',
            description: 'Everything has been read. Choose All to see earlier notifications.',
            clearable: false,
        };
    }
    if (view.status === 'read') {
        return {
            title: 'No read notifications',
            description: 'Notifications you have read stay here until you dismiss them.',
            clearable: false,
        };
    }
    return {
        title: "You're all caught up",
        description: 'Replies, approvals, shares and document updates will appear here.',
        clearable: false,
    };
}
