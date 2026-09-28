// notificationLinks.ts
// Where a notification's link leads in V2, or why it does not lead anywhere.
//
// Notification links are written by the server for the classic interface, so most of them
// name classic pages: `/chats?conversationId=`, `/group_workspaces`, `/profile?tab=violations`.
// Every spelling the classic resolver accepts (static/js/notifications.js,
// resolveNotificationNavigationTarget) is accepted here too and translated to its V2 route
// where one exists. A page V2 has not rebuilt yet -- approvals, workflow activity -- is opened
// in the classic interface rather than dropped, so no notice becomes a dead end.
//
// Two rules are stricter than classic's, deliberately. A link must stay on this site: the
// classic resolver will follow an absolute link to another origin, but a notification can
// quote content from outside, and following it off-site is never what a notice about your
// own work means. And a link that fails a check is reported, not guessed at.

import type { AppNotification } from './notifications';
import { readConversationParam } from './conversationUrl';
import { groupWorkspaceDocumentPath, groupWorkspacePath } from './groupWorkspaceNavigation';
import { publicWorkspacePath } from './publicWorkspaceNavigation';
import { requireWorkspaceId } from './workspaceContext';

export type NotificationTarget =
    /** A conversation, opened on the chat page. */
    | { kind: 'conversation'; conversationId: string }
    /** A V2 route, relative to the router's `/v2` base. */
    | { kind: 'route'; path: string }
    /**
     * A classic page, opened with a full navigation.
     *
     * `groupId` is the group the notice is about. Classic makes it the active group before
     * following the link, because classic group pages act on the active group rather than on
     * a group named in their URL.
     */
    | { kind: 'classic'; href: string; groupId: string | null };

export interface ResolvedNotificationLink {
    target: NotificationTarget | null;
    /** Why a link that is present will not be followed. Null when there is no link at all. */
    error: string | null;
}

const NO_LINK: ResolvedNotificationLink = { target: null, error: null };

const INVALID_LINK = 'This notification has an invalid link. Open the destination directly.';
const UNSUPPORTED_LINK = 'This notification has an unsupported link. Open the destination directly.';
const OFF_SITE_LINK = 'This notification links to another site, so it is not opened from here.';
const GROUP_DOCUMENT_MISMATCH =
    'This notification does not match its group and document. Refresh notifications or open the workspace directly.';

/** The id, when it is one a path segment can safely carry; null otherwise. */
function safeId(value: unknown): string | null {
    if (typeof value !== 'string') {
        return null;
    }
    try {
        return requireWorkspaceId(value);
    } catch {
        return null;
    }
}

function route(path: string): ResolvedNotificationLink {
    return { target: { kind: 'route', path }, error: null };
}

/**
 * The V2 route for one workflow run, once there is one.
 *
 * Phase 6b adds the run page at `/workspace/workflows/:workflowId/runs/:runId`. Until then
 * this returns null and a workflow-activity link keeps opening the classic page. Filling
 * this in is the whole change needed to move those links, and a workflow notice with a run
 * but no link at all, into V2.
 */
export function v2WorkflowRunPath(workflowId: string | null, runId: string | null): string | null {
    void workflowId;
    void runId;
    return null;
}

function groupIdFor(notification: AppNotification): string | null {
    return safeId(notification.link_context.group_id) ?? safeId(notification.metadata.group_id);
}

/**
 * A chat link. The conversation id is read with both spellings in circulation, the same
 * way the chat page reads it (conversationUrl.ts readConversationParam).
 */
function chatTarget(url: URL): ResolvedNotificationLink {
    const conversationId = readConversationParam(url.searchParams);
    if (!conversationId) {
        return route('/chat');
    }
    const id = safeId(conversationId);
    if (!id) {
        return { target: null, error: INVALID_LINK };
    }
    return { target: { kind: 'conversation', conversationId: id }, error: null };
}

/**
 * A link into a group's documents written for V2 (functions_group_document_publication.py and
 * functions_group_document_collaboration.py). Checked exactly as classic checks it: the path's
 * group, the single document id and the notice's own context all have to agree, because a
 * document link that disagrees with its notice would open the wrong group's document.
 */
function nativeGroupDocumentTarget(url: URL, notification: AppNotification): ResolvedNotificationLink {
    const match = url.pathname.match(/^\/v2\/groups\/([^/]+)\/documents\/?$/);
    let groupId: string | null = null;
    if (match) {
        try {
            groupId = safeId(decodeURIComponent(match[1]));
        } catch {
            groupId = null;
        }
    }
    const ids = url.searchParams.getAll('document_id');
    const documentId = ids.length === 1 ? safeId(ids[0]) : null;
    const context = notification.link_context;
    if (!groupId || !documentId || context.workspace_type !== 'group'
        || context.group_id !== groupId || context.document_id !== documentId
        || url.searchParams.has('group_id') || url.searchParams.has('group_ids')) {
        return { target: null, error: GROUP_DOCUMENT_MISMATCH };
    }
    return route(groupWorkspaceDocumentPath(groupId, documentId));
}

/**
 * Whether a `/v2/groups` link is about a document, using classic's test for the same thing.
 * A workflow link that happens to carry a `document_id` is not.
 */
function looksLikeGroupDocument(url: URL): boolean {
    const path = url.pathname.replace(/\/+/g, '/');
    if (!/^\/v2\/groups(?:\/|$)/i.test(path)) {
        return false;
    }
    const workflowLink = /^\/v2\/groups\/[^/]+\/workflows(?:\/[^/]+)?\/?$/.test(url.pathname);
    return /(?:^|\/)documents(?:\/|$)/i.test(path)
        || (url.searchParams.has('document_id') && !workflowLink);
}

function classic(url: URL, notification: AppNotification): ResolvedNotificationLink {
    return {
        target: {
            kind: 'classic',
            href: `${url.pathname}${url.search}${url.hash}`,
            groupId: groupIdFor(notification),
        },
        error: null,
    };
}

/**
 * Resolve a notification's link.
 *
 * `origin` is the page's own origin. It is a parameter so the resolver can be exercised
 * without a browser; callers pass `window.location.origin`.
 */
export function resolveNotificationLink(
    notification: AppNotification,
    origin: string,
): ResolvedNotificationLink {
    const raw = notification.link_url;
    if (!raw) {
        const runPath = v2WorkflowRunPath(
            safeId(notification.metadata.workflow_id),
            safeId(notification.metadata.run_id),
        );
        return runPath ? route(runPath) : NO_LINK;
    }
    if (!raw.trim()) {
        return { target: null, error: INVALID_LINK };
    }

    let url: URL;
    try {
        // Parsed against the page rather than inspected as a string: the URL parser is what
        // the browser will use to follow the link, so `//host`, `/\host` and `https:host`
        // resolve here exactly as they would on navigation.
        url = new URL(raw, origin);
    } catch {
        return { target: null, error: INVALID_LINK };
    }
    if ((url.protocol !== 'http:' && url.protocol !== 'https:') || url.username || url.password) {
        return { target: null, error: UNSUPPORTED_LINK };
    }
    if (url.origin !== origin) {
        return { target: null, error: OFF_SITE_LINK };
    }

    const path = url.pathname.replace(/\/{2,}/g, '/').replace(/(.)\/$/, '$1');

    // A Microsoft 365 action waiting in a conversation is resolved on the classic chat page,
    // which is the only one that renders the pending-action card.
    if ((path === '/chats' || path === '/chat' || path === '/v2/chat') && url.searchParams.has('m365_pending_action')) {
        return {
            target: {
                kind: 'classic',
                href: `/chats${url.search}${url.hash}`,
                groupId: groupIdFor(notification),
            },
            error: null,
        };
    }
    if (path === '/chats' || path === '/chat' || path === '/v2/chat') {
        return chatTarget(url);
    }

    if (looksLikeGroupDocument(url)) {
        return nativeGroupDocumentTarget(url, notification);
    }

    if (path === '/workflow-activity') {
        const runPath = v2WorkflowRunPath(
            safeId(url.searchParams.get('workflowId')),
            safeId(url.searchParams.get('runId')),
        );
        return runPath ? route(runPath) : classic(url, notification);
    }

    if (path === '/approvals') {
        return classic(url, notification);
    }

    // My Workspace has no per-document link, so a document notice opens the document list.
    if (path === '/workspace') {
        return route('/workspace/documents');
    }

    if (path === '/group_workspaces') {
        const groupId = groupIdFor(notification);
        return route(groupId ? groupWorkspacePath(groupId, 'documents') : '/groups');
    }

    const groupPage = path.match(/^\/groups\/([^/]+)$/);
    if (groupPage) {
        let groupId: string | null = null;
        try {
            groupId = safeId(decodeURIComponent(groupPage[1]));
        } catch {
            groupId = null;
        }
        return groupId ? route(groupWorkspacePath(groupId)) : { target: null, error: INVALID_LINK };
    }

    if (path === '/public_directory') {
        return route('/public/directory');
    }

    if (path === '/public_workspaces') {
        const workspaceId = safeId(notification.link_context.public_workspace_id);
        return route(workspaceId ? publicWorkspacePath(workspaceId) : '/public');
    }

    const publicPage = path.match(/^\/public_workspaces\/([^/]+)$/);
    if (publicPage) {
        let workspaceId: string | null = null;
        try {
            workspaceId = safeId(decodeURIComponent(publicPage[1]));
        } catch {
            workspaceId = null;
        }
        return workspaceId ? route(publicWorkspacePath(workspaceId)) : { target: null, error: INVALID_LINK };
    }

    if (path === '/profile') {
        return route(url.searchParams.get('tab') === 'violations' ? '/settings?tab=violations' : '/settings');
    }

    // Anything already written for V2 is a route in this application. The router adds its
    // own `/v2` base, so the prefix is removed rather than doubled.
    if (path === '/v2' || path.startsWith('/v2/')) {
        return route(`${path.slice(3) || '/'}${url.search}${url.hash}`);
    }

    // An API endpoint is never a page to open.
    if (path === '/api' || path.startsWith('/api/')) {
        return { target: null, error: UNSUPPORTED_LINK };
    }

    return classic(url, notification);
}
