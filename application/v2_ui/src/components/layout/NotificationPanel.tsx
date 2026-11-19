// NotificationPanel.tsx
// The list the bell opens: every notice for the signed-in user, newest first. Its footer leads
// to the Notifications page, which adds search, the read and unread filters and every page.
//
// Notification text is untrusted. A workflow alert or a reply preview can quote email or web
// content, so titles and messages are rendered as React text -- never as HTML or Markdown --
// and a link is followed only after notificationLinks.ts has checked it stays on this site.
// The rows themselves are NotificationRow, shared with that page.
//
// Drawn through a portal so it can extend past the rail, which is 68px wide when collapsed.

import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Bell, CheckCheck, RefreshCw, X } from 'lucide-react';
import { formatNotificationCount, type AppNotification } from '../../lib/notifications';
import { resolveNotificationLink, type ResolvedNotificationLink } from '../../lib/notificationLinks';
import { openNotificationTarget } from '../../lib/notificationNavigation';
import { workflowAlertServerActions } from '../../lib/workflowAlertActions';
import {
    refreshNotificationCount,
    subscribeNotificationCount,
    useNotificationStore,
} from '../../stores/notificationStore';
import { NotificationRow, notificationNeedsAcknowledgment } from '../notifications/NotificationRow';
import { Skeleton } from '../ui/primitives';

const PANEL_WIDTH = 384;

const iconButtonClass =
    'rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50';

export function NotificationPanel({
    id,
    anchorRef,
    onClose,
}: {
    id: string;
    anchorRef: RefObject<HTMLButtonElement>;
    /** `restoreFocus` is false when the reader dismissed the panel by clicking elsewhere. */
    onClose: (options?: { restoreFocus?: boolean }) => void;
}) {
    const navigate = useNavigate();
    const { pathname } = useLocation();
    const panelRef = useRef<HTMLDivElement>(null);
    const [position, setPosition] = useState({ top: 0, left: 0, width: PANEL_WIDTH, maxHeight: 560 });
    const [ackPending, setAckPending] = useState<Record<string, true>>({});

    const count = useNotificationStore((state) => state.count);
    const items = useNotificationStore((state) => state.items);
    const hasMore = useNotificationStore((state) => state.hasMore);
    const listLoading = useNotificationStore((state) => state.listLoading);
    const listLoaded = useNotificationStore((state) => state.listLoaded);
    const listError = useNotificationStore((state) => state.listError);
    const pendingIds = useNotificationStore((state) => state.pendingIds);
    const markingAll = useNotificationStore((state) => state.markingAll);
    const loadList = useNotificationStore((state) => state.loadList);
    const markRead = useNotificationStore((state) => state.markRead);
    const dismiss = useNotificationStore((state) => state.dismiss);
    const markAllRead = useNotificationStore((state) => state.markAllRead);

    const links = useMemo(() => {
        const origin = window.location.origin;
        return new Map(items.map((item) => [item.id, resolveNotificationLink(item, origin)]));
    }, [items]);

    // Opening the panel is the moment to be current, so both are read fresh.
    useEffect(() => {
        void loadList();
        void refreshNotificationCount('action');
    }, [loadList]);

    // A notice that arrives while the panel is open is shown rather than only counted.
    useEffect(
        () =>
            subscribeNotificationCount((change) => {
                if (change.rose) {
                    void useNotificationStore.getState().loadList();
                }
            }),
        [],
    );

    // Focus moves into the panel once, when it opens, so a screen reader announces it.
    useEffect(() => {
        panelRef.current?.focus();
    }, []);

    useEffect(() => {
        const measure = () => {
            const rect = anchorRef.current?.getBoundingClientRect();
            if (!rect) {
                return;
            }
            const width = Math.min(PANEL_WIDTH, window.innerWidth - 16);
            const top = Math.max(8, Math.min(rect.bottom + 8, window.innerHeight - 240));
            setPosition({
                top,
                left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
                width,
                maxHeight: Math.max(200, window.innerHeight - top - 16),
            });
        };
        const closeOutside = (event: PointerEvent) => {
            const target = event.target;
            if (target instanceof Node && !panelRef.current?.contains(target)
                && !anchorRef.current?.contains(target)) {
                onClose({ restoreFocus: false });
            }
        };
        // Captured at the document, ahead of every other Escape handler, so closing the panel
        // does not also close the mobile navigation it was opened from.
        const closeOnEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                onClose();
            }
        };
        measure();
        document.addEventListener('pointerdown', closeOutside);
        document.addEventListener('keydown', closeOnEscape, true);
        window.addEventListener('resize', measure);
        window.addEventListener('scroll', measure, true);
        return () => {
            document.removeEventListener('pointerdown', closeOutside);
            document.removeEventListener('keydown', closeOnEscape, true);
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
        };
    }, [anchorRef, onClose]);

    const open = async (notification: AppNotification, link: ResolvedNotificationLink) => {
        const target = link.target;
        if (!target) {
            return;
        }
        // Opening an alert that needs acknowledgment is a response to it, as on the alert card.
        const needsAcknowledgment = notificationNeedsAcknowledgment(notification);
        const settle = needsAcknowledgment
            ? workflowAlertServerActions.acknowledge([notification.id])
            : notification.is_read ? null : markRead(notification.id);
        // A full page load would cancel a request still on its way, so a notice that leaves
        // the application is settled first. Inside it the request carries on regardless.
        if (target.kind === 'classic' && settle) {
            await settle;
        }
        onClose();
        await openNotificationTarget(target, { navigate, pathname });
    };

    const acknowledge = async (notification: AppNotification) => {
        if (ackPending[notification.id]) {
            return;
        }
        setAckPending((current) => ({ ...current, [notification.id]: true }));
        try {
            // The shared action broadcasts the acknowledgment, which this tab's alert notice and
            // sound receive too, so the alert stops here and in every other tab straight away.
            const done = await workflowAlertServerActions.acknowledge([notification.id]);
            if (done.length) {
                await loadList();
            }
        } finally {
            setAckPending((current) => {
                const next = { ...current };
                delete next[notification.id];
                return next;
            });
        }
    };

    const hasUnread = (count ?? 0) > 0 || items.some((item) => !item.is_read);
    const headingId = `${id}-heading`;

    return createPortal(
        <div
            ref={panelRef}
            id={id}
            role="dialog"
            aria-labelledby={headingId}
            tabIndex={-1}
            data-notification-panel=""
            style={{ top: position.top, left: position.left, width: position.width, maxHeight: position.maxHeight }}
            className="glass-modal fixed z-[60] flex flex-col overflow-hidden rounded-2xl border border-edge shadow-xl outline-none"
        >
            <div className="flex shrink-0 items-center gap-2 border-b border-edge px-4 py-3">
                <h2 id={headingId} className="text-sm font-semibold text-text-1">
                    Notifications
                </h2>
                {count !== null && count > 0 && (
                    <span data-notification-panel-count="" className="text-xs text-text-3">
                        {formatNotificationCount(count)} unread
                    </span>
                )}
                <button
                    type="button"
                    data-notification-action="mark-all-read"
                    onClick={() => void markAllRead()}
                    disabled={markingAll || !hasUnread}
                    className="ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
                >
                    <CheckCheck size={14} />
                    Mark all read
                </button>
                <button
                    type="button"
                    onClick={() => onClose()}
                    aria-label="Close notifications"
                    className={iconButtonClass}
                >
                    <X size={15} />
                </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
                {items.length === 0 && listLoading && (
                    <div role="status" className="space-y-3 px-4 py-4">
                        <span className="sr-only">Loading notifications</span>
                        <Skeleton className="h-12 w-full" />
                        <Skeleton className="h-12 w-full" />
                        <Skeleton className="h-12 w-full" />
                    </div>
                )}

                {items.length === 0 && !listLoading && listError && (
                    <div role="alert" className="px-4 py-6 text-center">
                        <p className="text-sm text-text-2">{listError}</p>
                        <button
                            type="button"
                            onClick={() => void loadList()}
                            className="mt-3 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-accent hover:bg-accent-soft"
                        >
                            <RefreshCw size={13} />
                            Try again
                        </button>
                    </div>
                )}

                {items.length === 0 && !listLoading && !listError && listLoaded && (
                    <div data-notification-empty="" className="px-6 py-10 text-center">
                        <Bell size={22} aria-hidden="true" className="mx-auto mb-3 text-text-3" />
                        <p className="text-sm font-medium text-text-1">You're all caught up</p>
                        <p className="mt-1 text-xs text-text-3">
                            Replies, approvals, shares and document updates will appear here.
                        </p>
                    </div>
                )}

                {items.length > 0 && (
                    <ul aria-label="Notifications" className="divide-y divide-edge">
                        {items.map((item) => (
                            <NotificationRow
                                key={item.id}
                                notification={item}
                                link={links.get(item.id) ?? { target: null, error: null }}
                                pending={Boolean(pendingIds[item.id]) || Boolean(ackPending[item.id]) || markingAll}
                                onOpen={() => void open(item, links.get(item.id) ?? { target: null, error: null })}
                                onRead={() => void markRead(item.id)}
                                onAcknowledge={() => void acknowledge(item)}
                                onDismiss={() => {
                                    void dismiss(item.id);
                                    // The focused button is about to disappear with its row.
                                    panelRef.current?.focus();
                                }}
                            />
                        ))}
                    </ul>
                )}

                {items.length > 0 && listError && !listLoading && (
                    <p role="alert" className="px-4 py-2 text-xs text-danger">
                        {listError}
                    </p>
                )}

                {items.length > 0 && hasMore && (
                    <div className="px-4 py-3">
                        <button
                            type="button"
                            data-notification-action="load-more"
                            onClick={() => void loadList({ append: true })}
                            disabled={listLoading}
                            className="w-full rounded-lg px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {listLoading ? 'Loading…' : 'Load more'}
                        </button>
                    </div>
                )}
            </div>

            <div className="shrink-0 border-t border-edge px-4 py-2 text-right">
                {/* The page adds search, the read and unread filters and every page of the list. */}
                <Link
                    to="/notifications"
                    data-notification-view-all=""
                    onClick={() => onClose()}
                    className="text-xs text-text-3 hover:text-text-1 hover:underline"
                >
                    View all notifications
                </Link>
            </div>
        </div>,
        document.body,
    );
}
