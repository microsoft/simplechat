// NotificationRow.tsx
// One notification as a list item: what kind of notice it is, its title and message, when it
// arrived, and the actions on it.
//
// Shared by the bell's panel and the Notifications page, so a notice reads, opens, dismisses and
// is acknowledged the same way in both. The row only draws; what each action does is the
// caller's, because the panel closes itself after one and the page reloads its list.
//
// Notification text is untrusted. A workflow alert or a reply preview can quote email or web
// content, so the title and message are rendered as React text -- never as HTML or Markdown --
// and a link is followed only after notificationLinks.ts has checked it stays on this site.

import { clsx } from 'clsx';
import {
    Bell,
    Check,
    CheckCheck,
    ClipboardCheck,
    FileText,
    KeyRound,
    Megaphone,
    MessageSquareText,
    Share2,
    ShieldAlert,
    Users,
    Workflow,
    X,
} from 'lucide-react';
import {
    describeNotification,
    type AppNotification,
    type NotificationKind,
    type NotificationTone,
} from '../../lib/notifications';
import type { ResolvedNotificationLink } from '../../lib/notificationLinks';
import { formatRelativeTime } from '../../lib/userStats';

const KIND_ICONS: Record<NotificationKind, typeof Bell> = {
    approval: ClipboardCheck,
    reply: MessageSquareText,
    document: FileText,
    share: Share2,
    workflow: Workflow,
    workspace: Users,
    safety: ShieldAlert,
    security: KeyRound,
    announcement: Megaphone,
    other: Bell,
};

const TONE_CLASSES: Record<NotificationTone, string> = {
    ok: 'bg-ok-soft text-ok',
    info: 'bg-info-soft text-info',
    warn: 'bg-warn-soft text-warn',
    danger: 'bg-danger-soft text-danger',
    neutral: 'bg-surface-2 text-text-3',
};

const iconButtonClass =
    'rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50';

/**
 * Whether the notice is a workflow alert that is still waiting to be acknowledged.
 *
 * Opening such an alert is a response to it, as it is on the alert card, so every place that
 * opens a notice asks this first.
 */
export function notificationNeedsAcknowledgment(notification: AppNotification): boolean {
    return notification.notification_type === 'workflow_priority_alert'
        && notification.require_acknowledgment === true
        && notification.acknowledged !== true;
}

export function NotificationRow({
    notification,
    link,
    pending,
    onOpen,
    onRead,
    onDismiss,
    onAcknowledge,
    fullMessage = false,
}: {
    notification: AppNotification;
    link: ResolvedNotificationLink;
    /** A change to this notice is on its way, so its buttons wait for it. */
    pending: boolean;
    onOpen: () => void;
    onRead: () => void;
    onDismiss: () => void;
    onAcknowledge: () => void;
    /** Show the whole message. The panel is narrow, so by default it keeps to three lines. */
    fullMessage?: boolean;
}) {
    const described = describeNotification(notification);
    const Icon = KIND_ICONS[described.kind];
    const title = notification.title.trim() || described.label;
    const unread = !notification.is_read;
    const created = notification.created_at ? new Date(notification.created_at) : null;
    const createdValid = created !== null && !Number.isNaN(created.getTime());
    const needsAcknowledgment = notificationNeedsAcknowledgment(notification);
    const acknowledged = notification.notification_type === 'workflow_priority_alert'
        && notification.require_acknowledgment === true
        && notification.acknowledged === true;

    return (
        <li
            data-notification-id={notification.id}
            data-notification-type={notification.notification_type || undefined}
            data-unread={unread ? 'true' : 'false'}
            className={clsx('flex gap-3 px-4 py-3', unread && 'bg-accent-soft')}
        >
            <span
                aria-hidden="true"
                className={clsx(
                    'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                    TONE_CLASSES[described.tone],
                )}
            >
                <Icon size={15} />
            </span>
            <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-text-3 uppercase">
                    {unread && <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />}
                    <span className="truncate">{described.label}</span>
                    {needsAcknowledgment && (
                        <span
                            data-notification-ack-tag=""
                            className="rounded bg-danger-soft px-1.5 py-0.5 text-[10px] font-semibold text-danger"
                        >
                            Needs acknowledgment
                        </span>
                    )}
                    {unread && <span className="sr-only">(unread)</span>}
                </p>
                {link.target ? (
                    <button
                        type="button"
                        data-notification-action="open"
                        onClick={onOpen}
                        className="mt-0.5 block w-full rounded text-left text-sm font-medium break-words text-text-1 hover:text-accent hover:underline"
                    >
                        {title}
                    </button>
                ) : (
                    <p className="mt-0.5 text-sm font-medium break-words text-text-1">{title}</p>
                )}
                {notification.message && (
                    <p
                        className={clsx(
                            'mt-0.5 text-xs break-words whitespace-pre-line text-text-2',
                            !fullMessage && 'line-clamp-3',
                        )}
                    >
                        {notification.message}
                    </p>
                )}
                {link.error && (
                    <p data-notification-link-error="" className="mt-1 text-xs text-warn">
                        {link.error}
                    </p>
                )}
                {createdValid && (
                    <p className="mt-1 text-[11px] text-text-3">
                        <time dateTime={notification.created_at} title={created.toLocaleString()}>
                            {formatRelativeTime(notification.created_at)}
                        </time>
                    </p>
                )}
                {acknowledged && notification.acknowledged_by_name && notification.acknowledged_at && (
                    <p data-notification-acknowledged="" className="mt-1 text-[11px] text-text-3">
                        Acknowledged by {notification.acknowledged_by_name} at{' '}
                        <time dateTime={notification.acknowledged_at}>
                            {new Date(notification.acknowledged_at).toLocaleString()}
                        </time>
                    </p>
                )}
            </div>
            <div className="flex shrink-0 flex-col gap-0.5">
                {needsAcknowledgment && (
                    <button
                        type="button"
                        data-notification-action="acknowledge"
                        disabled={pending}
                        onClick={onAcknowledge}
                        aria-label={`Acknowledge: ${title}`}
                        title="Acknowledge"
                        className={iconButtonClass}
                    >
                        <CheckCheck size={14} />
                    </button>
                )}
                {unread && (
                    <button
                        type="button"
                        data-notification-action="read"
                        disabled={pending}
                        onClick={onRead}
                        aria-label={`Mark as read: ${title}`}
                        title="Mark as read"
                        className={iconButtonClass}
                    >
                        <Check size={14} />
                    </button>
                )}
                <button
                    type="button"
                    data-notification-action="dismiss"
                    disabled={pending}
                    onClick={onDismiss}
                    aria-label={`Dismiss: ${title}`}
                    title="Dismiss"
                    className={iconButtonClass}
                >
                    <X size={14} />
                </button>
            </div>
        </li>
    );
}
