// notifications.ts
// Types and calls for the notification routes in route_backend_notifications.py.
//
// The V2 bell reads the same notification documents the classic interface does, through the
// same routes. Nothing here is V2-specific on the server, which is what keeps the two
// interfaces agreeing on what is unread: marking a notice read in one clears it in the other.
//
// Every field is read defensively. A notification is written by many server features over a
// long time, so an old or partial document must render as an item with less detail rather
// than break the list. Its text is also untrusted: a workflow alert or a reply preview can
// quote email or web content, so callers render it as plain text and nothing else.

import { api } from './apiClient';

export interface NotificationLinkContext {
    workspace_type?: string;
    group_id?: string;
    public_workspace_id?: string;
    document_id?: string;
    conversation_id?: string;
    [key: string]: unknown;
}

export interface AppNotification {
    id: string;
    notification_type: string;
    title: string;
    message: string;
    created_at: string;
    is_read: boolean;
    link_url: string;
    link_context: NotificationLinkContext;
    metadata: Record<string, unknown>;
    /** Server-side presentation hint, e.g. `{ icon: 'bi-chat-dots', color: 'success' }`. */
    type_config: { icon?: string; color?: string };
    /** Workflow alerts only. */
    priority?: string;
    /** Workflow alerts only; `failure` marks a run that errored. */
    category?: string;
}

export interface NotificationPage {
    notifications: AppNotification[];
    page: number;
    hasMore: boolean;
}

/** One of the three page sizes the list route accepts (10, 20, 50). */
export const NOTIFICATION_PAGE_SIZE = 20;

/**
 * The count route stops counting here (functions_notifications.py get_unread_notification_count),
 * so a count at the cap means "this many or more" and is shown as `9+`.
 */
export const NOTIFICATION_COUNT_CAP = 10;

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

/** A notification document as the panel can safely use it, or null when it has no id. */
export function normalizeNotification(raw: unknown): AppNotification | null {
    if (!isRecord(raw)) {
        return null;
    }
    const id = text(raw.id).trim();
    if (!id) {
        return null;
    }
    const typeConfig = isRecord(raw.type_config) ? raw.type_config : {};
    return {
        id,
        notification_type: text(raw.notification_type),
        title: text(raw.title),
        message: text(raw.message),
        created_at: text(raw.created_at),
        is_read: raw.is_read === true,
        link_url: text(raw.link_url),
        link_context: isRecord(raw.link_context) ? (raw.link_context as NotificationLinkContext) : {},
        metadata: isRecord(raw.metadata) ? raw.metadata : {},
        type_config: {
            icon: text(typeConfig.icon) || undefined,
            color: text(typeConfig.color) || undefined,
        },
        priority: text(raw.priority) || undefined,
        category: text(raw.category) || undefined,
    };
}

/**
 * The unread count, or null when the response is not a count at all.
 *
 * Null is a signal rather than a zero. A session that expired mid-visit can be answered with
 * the sign-in page -- a successful response, just not JSON -- and treating that as "nothing
 * unread" would hide every notice while polling forever against a page that will never
 * answer.
 */
export function readNotificationCount(payload: unknown): number | null {
    if (!isRecord(payload) || typeof payload.count !== 'number' || !Number.isFinite(payload.count)) {
        return null;
    }
    return Math.max(0, Math.floor(payload.count));
}

export async function fetchNotificationCount(signal?: AbortSignal): Promise<number | null> {
    return readNotificationCount(await api.get<unknown>('/api/notifications/count', signal));
}

/** One page of notifications, read and unread, newest first. Dismissed ones are left out. */
export async function fetchNotificationPage(page: number, signal?: AbortSignal): Promise<NotificationPage> {
    const params = new URLSearchParams({
        page: String(page),
        per_page: String(NOTIFICATION_PAGE_SIZE),
        include_read: 'true',
        include_dismissed: 'false',
    });
    const payload = await api.get<unknown>(`/api/notifications?${params}`, signal);
    if (!isRecord(payload) || !Array.isArray(payload.notifications)) {
        throw new Error('Your notifications could not be read. Try again.');
    }
    return {
        notifications: payload.notifications
            .map(normalizeNotification)
            .filter((item): item is AppNotification => item !== null),
        page: typeof payload.page === 'number' ? payload.page : page,
        hasMore: payload.has_more === true,
    };
}

export const markNotificationRead = (notificationId: string) =>
    api.post<unknown>(`/api/notifications/${encodeURIComponent(notificationId)}/read`);

export const dismissNotification = (notificationId: string) =>
    api.delete<unknown>(`/api/notifications/${encodeURIComponent(notificationId)}/dismiss`);

export const markAllNotificationsRead = () => api.post<unknown>('/api/notifications/mark-all-read');

/** How the badge reads a count: the number itself, or `9+` at and above the server's cap. */
export function formatNotificationCount(count: number): string {
    return count >= NOTIFICATION_COUNT_CAP ? '9+' : String(count);
}

export type NotificationTone = 'ok' | 'info' | 'warn' | 'danger' | 'neutral';

export type NotificationKind =
    | 'approval'
    | 'reply'
    | 'document'
    | 'share'
    | 'workflow'
    | 'workspace'
    | 'safety'
    | 'security'
    | 'announcement'
    | 'other';

export interface NotificationDescription {
    kind: NotificationKind;
    /** Short type label shown above the title, e.g. "AI responded". */
    label: string;
    tone: NotificationTone;
}

const TONE_BY_COLOR: Record<string, NotificationTone> = {
    success: 'ok',
    info: 'info',
    warning: 'warn',
    danger: 'danger',
    secondary: 'neutral',
};

function describeType(type: string, category: string | undefined): Omit<NotificationDescription, 'tone'> {
    if (type === 'workflow_priority_alert') {
        return {
            kind: 'workflow',
            label: category === 'failure' ? 'Workflow run failed' : 'Workflow alert',
        };
    }
    // A chat-started run whose results could not be posted to its chat (functions_workflow_chat_delivery.py).
    if (type === 'workflow_chat_delivery') {
        return { kind: 'workflow', label: 'Workflow results' };
    }
    if (type.startsWith('m365_approval_')) {
        return { kind: 'approval', label: 'Microsoft 365 approval' };
    }
    if (type === 'chat_response_complete') {
        return { kind: 'reply', label: 'AI responded' };
    }
    if (type === 'collaboration_message_received') {
        return { kind: 'reply', label: 'Shared conversation' };
    }
    if (type === 'document_processing_complete') {
        return { kind: 'document', label: 'Document processed' };
    }
    if (type === 'document_processing_failed') {
        return { kind: 'document', label: 'Document failed' };
    }
    if (type === 'document_deletion_request') {
        return { kind: 'document', label: 'Deletion request' };
    }
    if (type.includes('_document_share_')) {
        const outcome = type.slice(type.lastIndexOf('_') + 1);
        const label = outcome === 'approved'
            ? 'Share approved'
            : outcome === 'denied'
              ? 'Share declined'
              : outcome === 'removed'
                ? 'Share removed'
                : 'Share request';
        return { kind: 'share', label };
    }
    if (type.startsWith('approval_request_')) {
        return { kind: 'approval', label: 'Approval request' };
    }
    if (type.startsWith('agent_template_')) {
        return { kind: 'approval', label: 'Agent template' };
    }
    if (type.startsWith('generated_file_approval_')) {
        return { kind: 'approval', label: 'File approval' };
    }
    if (type.startsWith('safety_violation_')) {
        return { kind: 'safety', label: 'Content safety' };
    }
    if (type === 'key_vault_secret_expiring') {
        return { kind: 'security', label: 'Secret expiring' };
    }
    if (type === 'system_announcement') {
        return { kind: 'announcement', label: 'Announcement' };
    }
    if (type === 'ownership_transfer_request') {
        return { kind: 'workspace', label: 'Ownership transfer' };
    }
    if (type === 'group_deletion_request') {
        return { kind: 'workspace', label: 'Group deletion' };
    }
    if (type.startsWith('group_')) {
        return { kind: 'workspace', label: 'Group' };
    }
    if (type === 'conversation_created') {
        return { kind: 'reply', label: 'Conversation' };
    }
    return { kind: 'other', label: 'Notification' };
}

/**
 * What a notification is, for its icon and label.
 *
 * The tone follows the server's own `type_config.color`, which for a workflow alert already
 * reflects its priority, so the panel and the classic list agree on how loud each item is.
 * The label always says what the item is as well: color alone never carries the meaning.
 */
export function describeNotification(notification: AppNotification): NotificationDescription {
    const described = describeType(notification.notification_type, notification.category);
    return {
        ...described,
        tone: TONE_BY_COLOR[notification.type_config.color ?? ''] ?? 'info',
    };
}
