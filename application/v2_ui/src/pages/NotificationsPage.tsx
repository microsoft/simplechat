// NotificationsPage.tsx
// The full Notifications page: every notice for the signed-in user, with the filters, the search
// and the numbered pages the bell's panel has no room for.
//
// The V2 counterpart of classic `/notifications`. It reads and writes the same notification
// documents through the same routes, so a notice read, dismissed or acknowledged here is read,
// dismissed or acknowledged in classic and in the bell too.
//
// Classic filters and searches only the page it has fetched, so its totals and page links
// describe the wrong list. Here the read filter and the search go to the server with the page
// that is asked for (`status` and `q` on GET /api/notifications), and the server applies them
// before it pages, so "Showing 21-40 of 45" and the page numbers describe what matched.
//
// What is shown is kept in the address -- `?status=&q=&page=&per_page=` -- so Back, a bookmark
// and a shared link reopen the same view. The page size is the exception that is also
// remembered: it starts from the reader's saved `notifications_per_page`, and choosing another
// saves it, exactly as classic does.
//
// Notification text is untrusted: a workflow alert or a reply preview can quote email or web
// content. It is rendered as React text by NotificationRow, never as markup, and a notice's link
// is followed only after notificationLinks.ts has checked that it stays on this site.
//
// Keyboard focus stays where the reader put it. A browser takes focus from a button that becomes
// disabled and leaves it on the page, so the controls that can be unavailable -- the pager's end
// stops, Refresh, Mark all read -- say so with aria-disabled and ignore the press instead. Where a
// control goes away with the thing it acted on, as a row's button or Try again does, focus is
// moved to the list, or back to the button if it returns.

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Bell, CheckCheck, RefreshCw, Search, X } from 'lucide-react';
import { clsx } from 'clsx';
import { NotificationRow, notificationNeedsAcknowledgment } from '../components/notifications/NotificationRow';
import { NotificationsHeader } from '../components/notifications/NotificationsHeader';
import { NotificationsPager } from '../components/notifications/NotificationsPager';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import { SectionError } from '../components/workspace/primitives';
import { resolveNotificationLink, type ResolvedNotificationLink } from '../lib/notificationLinks';
import { openNotificationTarget } from '../lib/notificationNavigation';
import {
    dismissNotification,
    markNotificationRead,
    saveNotificationsPerPage,
    type AppNotification,
} from '../lib/notifications';
import {
    DEFAULT_NOTIFICATIONS_PAGE_SIZE,
    NOTIFICATIONS_PAGE_SIZES,
    NOTIFICATIONS_SEARCH_MAX_LENGTH,
    clampNotificationsPage,
    describeEmptyNotifications,
    describeNotificationResults,
    normalizeNotificationsPageSize,
    normalizeNotificationsQuery,
    notificationsPageCount,
    notificationsScopeKey,
    notificationsViewKey,
    notificationsViewParams,
    parseNotificationsView,
    resolveNotificationsPageSize,
    type NotificationStatus,
    type NotificationsView,
} from '../lib/notificationsPage';
import { useNotificationsList, type NotificationsListResult } from '../lib/useNotificationsList';
import { workflowAlertServerActions } from '../lib/workflowAlertActions';
import { refreshNotificationCount, useNotificationStore } from '../stores/notificationStore';
import { toast } from '../stores/toastStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';

/** How long typing pauses before the search is sent, so a word is one read rather than one per letter. */
const SEARCH_DEBOUNCE_MS = 400;

/** What the Unread list already says when it has nothing to show, and what Mark all read leaves true. */
const NO_UNREAD = describeNotificationResults({
    total: 0,
    page: 1,
    perPage: DEFAULT_NOTIFICATIONS_PAGE_SIZE,
    status: 'unread',
    query: '',
});

const STATUS_OPTIONS: { id: NotificationStatus; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'unread', label: 'Unread' },
    { id: 'read', label: 'Read' },
];

/** Waits for the page to be drawn, but never for a hidden tab, which draws nothing. */
function afterRender(): Promise<void> {
    return new Promise((resolve) => {
        const timer = window.setTimeout(resolve, 100);
        window.requestAnimationFrame(() => {
            window.clearTimeout(timer);
            resolve();
        });
    });
}

/**
 * Change one notice on the server. A refusal is reported in the server's own words, as the
 * bell's panel reports it, and the bell's count is read again whichever way it went, so the
 * badge agrees with the server without this page working the count out for itself.
 */
async function changeNotice(
    change: (notificationId: string) => Promise<unknown>,
    notificationId: string,
    fallback: string,
): Promise<boolean> {
    try {
        await change(notificationId);
        return true;
    } catch (error) {
        toast.error(error instanceof Error && error.message ? error.message : fallback);
        return false;
    } finally {
        void refreshNotificationCount('action');
    }
}

const readOne = (notificationId: string) =>
    changeNotice(markNotificationRead, notificationId, 'That notification could not be marked as read.');
const dismissOne = (notificationId: string) =>
    changeNotice(dismissNotification, notificationId, 'That notification could not be dismissed.');

export function NotificationsPage() {
    const navigate = useNavigate();
    const { pathname } = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const view = useMemo(() => parseNotificationsView(searchParams), [searchParams]);

    // The saved size decides when the address names none, so the first read waits for the
    // preferences to arrive rather than reading twenty and then reading again.
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    const savedPerPage = useUserSettingsStore((state) => state.settings.notifications_per_page);
    const perPage = view.perPage ?? (settingsLoading ? null : resolveNotificationsPageSize(null, savedPerPage));
    const listView = perPage === null ? null : { ...view, perPage };
    const key = listView ? notificationsViewKey(listView) : null;

    const { result, loading, error, reload } = useNotificationsList(listView);
    // An answer for an earlier view is not an answer for this one.
    const current = result && result.key === key ? result : null;
    const items = useMemo(() => current?.items ?? [], [current]);
    // An address past the last page is answered with no rows and the real total. The page then moves
    // to the last page, and until it has, nothing is drawn that would read as an empty list.
    const pastTheEnd = current !== null && current.items.length === 0 && current.total > 0 && view.page > 1;
    // The pager stays on screen, with its count, while another page of the same list is on its way.
    const pagerSource = current
        ?? (result && listView && result.scope === notificationsScopeKey(listView) ? result : null);
    const pageCount = pagerSource ? notificationsPageCount(pagerSource.total, pagerSource.perPage) : 1;

    const bellCount = useNotificationStore((state) => state.count);
    const markingAll = useNotificationStore((state) => state.markingAll);
    const hasUnread = (bellCount ?? 0) > 0 || items.some((item) => !item.is_read);
    const [pendingIds, setPendingIds] = useState<Record<string, true>>({});
    /** The list Mark all read emptied of unread notices, which the line above it says so for. */
    const [allReadAnswer, setAllReadAnswer] = useState<NotificationsListResult | null>(null);

    const searchId = useId();
    const headingId = useId();
    const searchRef = useRef<HTMLInputElement>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const resultsRef = useRef<HTMLElement>(null);
    const [searchInput, setSearchInput] = useState(view.query);
    /** The search the address holds, or is about to: what typing is compared with. */
    const committedQuery = useRef(view.query);

    const links = useMemo(() => {
        const origin = window.location.origin;
        return new Map(items.map((item) => [item.id, resolveNotificationLink(item, origin)]));
    }, [items]);

    const updateView = useCallback(
        (change: Partial<NotificationsView>, replace = false) => {
            setSearchParams(
                (previous) => notificationsViewParams({ ...parseNotificationsView(previous), ...change }),
                { replace },
            );
        },
        [setSearchParams],
    );

    // The bell's count is read afresh on arriving, as it is when the panel opens, so the badge
    // and this page agree from the start.
    useEffect(() => {
        void refreshNotificationCount('action');
    }, []);

    // An address change the page did not make itself -- Back, Forward, a link -- replaces what
    // was typed.
    useEffect(() => {
        if (view.query !== committedQuery.current) {
            committedQuery.current = view.query;
            setSearchInput(view.query);
        }
    }, [view.query]);

    const commitSearch = useCallback(
        (value: string) => {
            const next = normalizeNotificationsQuery(value);
            if (next === committedQuery.current) {
                return;
            }
            committedQuery.current = next;
            // Replaced rather than pushed, so Back leaves the page instead of undoing a letter.
            updateView({ query: next, page: 1 }, true);
        },
        [updateView],
    );

    useEffect(() => {
        if (normalizeNotificationsQuery(searchInput) === committedQuery.current) {
            return undefined;
        }
        const timer = window.setTimeout(() => commitSearch(searchInput), SEARCH_DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [searchInput, commitSearch]);

    // Filtering or searching can leave fewer pages than the one asked for, and so can acting on
    // the last notice on the last page. The list then answers with no rows and a total, and the
    // page moves to the last page that has some.
    useEffect(() => {
        if (!current || loading || current.items.length > 0 || current.total === 0 || view.page <= 1) {
            return;
        }
        const last = clampNotificationsPage(view.page, current.total, current.perPage);
        if (last !== view.page) {
            updateView({ page: last }, true);
        }
    }, [current, loading, view.page, updateView]);

    const clearSearch = () => {
        setSearchInput('');
        commitSearch('');
        searchRef.current?.focus();
    };

    const changePerPage = (value: string) => {
        const next = normalizeNotificationsPageSize(value);
        if (next === null || next === perPage) {
            return;
        }
        updateView({ perPage: next, page: 1 });
        saveNotificationsPerPage(next).then(
            () => {
                // Kept in the preferences already loaded, so the next visit starts from it too.
                useUserSettingsStore.setState((state) => ({
                    settings: { ...state.settings, notifications_per_page: next },
                }));
            },
            () => toast.error('Your page size could not be saved. It applies to this visit only.'),
        );
    };

    const changePage = (page: number) => {
        updateView({ page });
        // The next page starts at its top. Focus is left on the pager button that was used, so
        // stepping through the pages from the keyboard goes on from where it was.
        scrollRef.current?.scrollTo({ top: 0 });
    };

    /** Move focus to the row's first control, or the list, when the button pressed has gone. */
    const recoverFocus = async (id: string) => {
        await afterRender();
        const active = document.activeElement;
        if (active && active !== document.body) {
            return;
        }
        const row = [...(resultsRef.current?.querySelectorAll<HTMLElement>('li[data-notification-id]') ?? [])]
            .find((element) => element.dataset.notificationId === id);
        const control = row?.querySelector<HTMLElement>('[data-notification-action]:not(:disabled)');
        (control ?? resultsRef.current)?.focus({ preventScroll: true });
    };

    /** Change one notice on the server, then show the list as the server now has it. */
    const act = async (notification: AppNotification, perform: () => Promise<unknown>) => {
        if (pendingIds[notification.id]) {
            return;
        }
        setPendingIds((ids) => ({ ...ids, [notification.id]: true }));
        try {
            // The shared actions report their own failures and keep the bell's count right.
            await perform();
        } finally {
            setPendingIds((ids) => {
                const next = { ...ids };
                delete next[notification.id];
                return next;
            });
        }
        await reload();
        void recoverFocus(notification.id);
    };

    const markAllRead = async () => {
        const marked = await useNotificationStore.getState().markAllRead();
        const answer = await reload();
        // Said for this list only. The next read of any view is a new answer, so it is not said again.
        setAllReadAnswer(marked ? answer : null);
    };

    /**
     * Read the list again from the explanation of a failed read.
     *
     * The explanation, and the button on it, go while the read is on its way, so the keyboard waits
     * in the list rather than being dropped on the page. A read that fails again brings the button
     * back, and the keyboard returns to it.
     */
    const tryAgain = async () => {
        const active = document.activeElement;
        if (active instanceof HTMLElement && active.closest('[data-notifications-error]')) {
            resultsRef.current?.focus({ preventScroll: true });
        }
        await reload();
        await afterRender();
        const parked = document.activeElement === resultsRef.current || document.activeElement === document.body;
        const again = resultsRef.current?.querySelector<HTMLElement>('[data-notifications-error] button');
        if (parked && again) {
            again.focus({ preventScroll: true });
        }
    };

    const open = async (notification: AppNotification, link: ResolvedNotificationLink) => {
        const target = link.target;
        if (!target) {
            return;
        }
        // Opening an alert that needs acknowledgment is a response to it, as on the alert card.
        const settle = notificationNeedsAcknowledgment(notification)
            ? workflowAlertServerActions.acknowledge([notification.id])
            : notification.is_read ? null : readOne(notification.id);
        // A full page load would cancel a request still on its way, so a notice that leaves the
        // application is settled first. Inside it the request carries on regardless.
        if (target.kind === 'classic' && settle) {
            await settle;
        }
        await openNotificationTarget(target, { navigate, pathname });
    };

    const summary = current && !pastTheEnd
        ? describeNotificationResults({
            total: current.total,
            page: view.page,
            perPage: current.perPage,
            status: view.status,
            query: view.query,
        })
        : '';
    // Mark all read leaves every notification read, which the list may not otherwise say. The sentence
    // is the one an empty Unread list already uses, and it goes with the list it was said for.
    const announcement = summary && current === allReadAnswer && summary !== NO_UNREAD
        ? `${summary} ${NO_UNREAD}`
        : summary;
    const empty = describeEmptyNotifications(view);
    const waiting = (!current && !error) || pastTheEnd;
    const tryAgainButton = (
        <GlassButton size="sm" onClick={() => void tryAgain()}>
            <RefreshCw size={14} aria-hidden="true" />
            Try again
        </GlassButton>
    );

    return (
        <div data-testid="v2-notifications-page" className="flex h-full min-h-0 flex-col">
            <NotificationsHeader
                title="Notifications"
                description="Replies, approvals, shares, document updates and workflow alerts for your account."
                actions={[
                    {
                        id: 'mark-all-read',
                        label: 'Mark all read',
                        icon: <CheckCheck size={14} />,
                        onClick: () => void markAllRead(),
                        disabled: markingAll || !hasUnread,
                        testId: 'notifications-mark-all-read',
                    },
                    {
                        id: 'refresh',
                        label: 'Refresh',
                        icon: <RefreshCw size={14} />,
                        onClick: () => void reload(),
                        loading: loading && current !== null,
                        testId: 'notifications-refresh',
                    },
                ]}
            />
            <div
                ref={scrollRef}
                data-testid="notifications-page-scroll"
                className="min-h-0 flex-1 overflow-y-auto px-4 py-5 lg:px-6"
            >
                <div className="mx-auto w-full max-w-4xl space-y-4 pb-10">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-3">
                        <div
                            role="group"
                            aria-label="Show notifications"
                            className="inline-flex max-w-full rounded-xl border border-edge bg-surface-1 p-0.5"
                        >
                            {STATUS_OPTIONS.map((option) => (
                                <button
                                    key={option.id}
                                    type="button"
                                    data-notification-filter={option.id}
                                    aria-pressed={view.status === option.id}
                                    onClick={() => updateView({ status: option.id, page: 1 })}
                                    className={clsx(
                                        'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors max-md:min-h-11 max-md:px-4',
                                        view.status === option.id
                                            ? 'bg-accent text-on-accent'
                                            : 'text-text-2 hover:text-text-1',
                                    )}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>

                        <div className="relative min-w-[14rem] flex-1">
                            <label htmlFor={searchId} className="sr-only">
                                Search notifications
                            </label>
                            <Search
                                size={15}
                                aria-hidden="true"
                                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                            />
                            <input
                                id={searchId}
                                ref={searchRef}
                                type="search"
                                value={searchInput}
                                maxLength={NOTIFICATIONS_SEARCH_MAX_LENGTH}
                                autoComplete="off"
                                spellCheck={false}
                                placeholder="Search notifications"
                                onChange={(event) => setSearchInput(event.target.value)}
                                onKeyDown={(event) => {
                                    // Enter searches now rather than waiting out the pause.
                                    if (event.key === 'Enter') {
                                        event.preventDefault();
                                        commitSearch(searchInput);
                                    }
                                }}
                                className="w-full rounded-xl border border-edge bg-surface-1 py-2 pr-9 pl-9 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none max-md:min-h-11 max-md:text-base [&::-webkit-search-cancel-button]:hidden"
                            />
                            {searchInput && (
                                <button
                                    type="button"
                                    aria-label="Clear search"
                                    onClick={clearSearch}
                                    className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-lg p-1.5 text-text-3 hover:bg-surface-2 hover:text-text-1"
                                >
                                    <X size={14} aria-hidden="true" />
                                </button>
                            )}
                        </div>

                        <label className="flex items-center gap-2 text-xs text-text-3">
                            <span>Per page</span>
                            <select
                                value={perPage ?? ''}
                                disabled={perPage === null}
                                onChange={(event) => changePerPage(event.target.value)}
                                className="rounded-xl border border-edge bg-surface-1 px-2.5 py-2 text-sm text-text-1 focus:border-accent focus:outline-none disabled:opacity-60 max-md:min-h-11 max-md:text-base"
                            >
                                {perPage === null && <option value="">…</option>}
                                {NOTIFICATIONS_PAGE_SIZES.map((size) => (
                                    <option key={size} value={size}>
                                        {size}
                                    </option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <p
                        role="status"
                        aria-live="polite"
                        aria-atomic="true"
                        data-notifications-summary=""
                        className="min-h-4 text-xs text-text-3"
                    >
                        {announcement}
                    </p>

                    <section
                        ref={resultsRef}
                        tabIndex={-1}
                        aria-labelledby={headingId}
                        aria-busy={loading || waiting}
                        data-testid="notifications-results"
                        className="space-y-3 outline-none"
                    >
                        <h2 id={headingId} className="sr-only">
                            Your notifications
                        </h2>

                        {waiting && (
                            <>
                                <span className="sr-only">Loading notifications</span>
                                <div aria-hidden="true" data-notifications-loading="" className="space-y-2">
                                    {[0, 1, 2, 3].map((index) => (
                                        <Skeleton key={index} className="h-20 w-full" />
                                    ))}
                                </div>
                            </>
                        )}

                        {!current && error && (
                            <div data-notifications-error="">
                                <SectionError message={error} action={tryAgainButton} />
                            </div>
                        )}

                        {current && error && (
                            <div data-notifications-error="">
                                <SectionError
                                    message={`${error} What is shown may be out of date.`}
                                    action={tryAgainButton}
                                />
                            </div>
                        )}

                        {current && items.length === 0 && !pastTheEnd && (
                            <div data-notification-empty="">
                                <EmptyState
                                    icon={<Bell size={28} aria-hidden="true" />}
                                    title={empty.title}
                                    description={empty.description}
                                    action={
                                        empty.clearable ? (
                                            <GlassButton size="sm" variant="subtle" onClick={clearSearch}>
                                                Clear search
                                            </GlassButton>
                                        ) : undefined
                                    }
                                />
                            </div>
                        )}

                        {current && items.length > 0 && (
                            <GlassPanel elevation="flat" className="overflow-hidden">
                                <ul
                                    aria-label="Notifications"
                                    data-testid="notifications-list"
                                    className={clsx('divide-y divide-edge transition-opacity', loading && 'opacity-70')}
                                >
                                    {items.map((item) => {
                                        const link = links.get(item.id) ?? { target: null, error: null };
                                        return (
                                            <NotificationRow
                                                key={item.id}
                                                notification={item}
                                                link={link}
                                                fullMessage
                                                pending={Boolean(pendingIds[item.id]) || markingAll}
                                                onOpen={() => void open(item, link)}
                                                onRead={() => void act(item, () => readOne(item.id))}
                                                onDismiss={() => void act(item, () => dismissOne(item.id))}
                                                onAcknowledge={() =>
                                                    void act(item, () => workflowAlertServerActions.acknowledge([item.id]))
                                                }
                                            />
                                        );
                                    })}
                                </ul>
                            </GlassPanel>
                        )}
                    </section>

                    {pagerSource && (
                        <NotificationsPager
                            page={Math.min(view.page, pageCount)}
                            pageCount={pageCount}
                            onPageChange={changePage}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}
