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
//
// Staying on this site is checked on the address that is actually followed, not only on the
// link as written. A same-origin link can still carry a path that, copied into a new address,
// names another site -- `/.//host` parses to the path `//host` -- so every classic address is
// read back before it is used, and read back again just before the page is left.

import type { AppNotification } from './notifications';
import type { WorkflowScope } from './workflowEditor';
import { readConversationParam } from './conversationUrl';
import { groupWorkspaceDocumentPath, groupWorkspacePath } from './groupWorkspaceNavigation';
import { publicWorkspacePath } from './publicWorkspaceNavigation';
import { workflowRunHref } from './workflowRunLink';
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
export const OFF_SITE_LINK = 'This notification links to another site, so it is not opened from here.';
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
 * The V2 route for one workflow run: the Workflows section of the workspace the workflow lives
 * in, with that workflow's run history open and the run expanded (workflowRunLink.ts). There
 * is no separate `/runs/:runId` route; the section reads the run from its query, in personal
 * and group workspaces alike.
 *
 * Null when the workspace, the workflow or the run is unknown, or an id is one a link must not
 * carry. The caller then keeps the classic link, or offers none, rather than guessing where
 * the run lives.
 */
export function v2WorkflowRunPath(
    scope: WorkflowScope | null,
    workflowId: string | null,
    runId: string | null,
): string | null {
    const workflow = safeId(workflowId);
    const run = safeId(runId);
    // Checked here as well as typed: workflowRunHref reads anything that is not a group as personal.
    if (!scope || (scope.type !== 'personal' && scope.type !== 'group') || !workflow || !run) {
        return null;
    }
    try {
        return workflowRunHref(workflow, run, scope);
    } catch {
        return null;
    }
}

/**
 * The notice types written about one workflow run: a workflow's own alerts
 * (functions_workflow_runner.py) and the notices about a chat-started run whose results could
 * not be posted to its chat (functions_workflow_chat_delivery.py). Only these open the run when
 * they carry no link of their own; any other notice that happens to name a run does not.
 */
const WORKFLOW_NOTIFICATION_TYPES: ReadonlySet<string> = new Set([
    'workflow_priority_alert',
    'workflow_chat_delivery',
]);

/**
 * Whether the notice is about a Microsoft 365 action. Those are resolved on classic pages,
 * which are the only ones that render the pending action, wherever the action id was written.
 */
function isMicrosoft365Notice(notification: AppNotification): boolean {
    return 'm365_pending_action_id' in notification.metadata
        || 'm365_pending_action_id' in notification.link_context;
}

function scopeOf(type: unknown, groupId: unknown): WorkflowScope | null {
    if (type === 'personal') {
        return { type: 'personal' };
    }
    if (type === 'group') {
        const id = safeId(groupId);
        return id ? { type: 'group', groupId: id } : null;
    }
    return null;
}

/**
 * The workspace the notice says its workflow lives in (`workflow_scope` and
 * `workflow_group_id`). Never `group_id`: that is the group classic makes active when the
 * notice opens, not a claim about where the workflow lives.
 */
function noticeWorkflowScope(notification: AppNotification): WorkflowScope | null {
    return scopeOf(notification.metadata.workflow_scope, notification.metadata.workflow_group_id);
}

function linkWorkflowScope(url: URL): WorkflowScope | null {
    return scopeOf(url.searchParams.get('scope'), url.searchParams.get('groupId'));
}

function sameScope(left: WorkflowScope, right: WorkflowScope): boolean {
    if (left.type === 'group' || right.type === 'group') {
        return left.type === 'group' && right.type === 'group' && left.groupId === right.groupId;
    }
    return true;
}

/** Whether the notice's own id, when it wrote one, agrees with the id its link names. */
function agreesWithNotice(written: unknown, linked: string): boolean {
    return written === undefined || written === null || written === '' || written === linked;
}

/**
 * The V2 run a classic workflow-activity link names, or null to keep the classic page.
 *
 * Opened in V2 only when the link and the notice agree on everything: the workspace the
 * workflow lives in, the workflow and the run. A Microsoft 365 notice stays classic.
 */
function workflowActivityRunPath(url: URL, notification: AppNotification): string | null {
    if (isMicrosoft365Notice(notification)) {
        return null;
    }
    const linked = linkWorkflowScope(url);
    const written = noticeWorkflowScope(notification);
    const workflowId = safeId(url.searchParams.get('workflowId'));
    const runId = safeId(url.searchParams.get('runId'));
    if (!linked || !written || !sameScope(linked, written) || !workflowId || !runId
        || !agreesWithNotice(notification.metadata.workflow_id, workflowId)
        || !agreesWithNotice(notification.metadata.run_id, runId)) {
        return null;
    }
    return v2WorkflowRunPath(linked, workflowId, runId);
}

/** The run a workflow notice without a link of its own is about, or null for no link. */
function unlinkedRunPath(notification: AppNotification): string | null {
    if (!WORKFLOW_NOTIFICATION_TYPES.has(notification.notification_type) || isMicrosoft365Notice(notification)) {
        return null;
    }
    return v2WorkflowRunPath(
        noticeWorkflowScope(notification),
        safeId(notification.metadata.workflow_id),
        safeId(notification.metadata.run_id),
    );
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

/**
 * Why a path on this site is still not followed, or null when it is a path the server writes.
 *
 * The URL parser has already resolved the path's dot segments, `%2e` spellings included, and
 * turned its backslashes into slashes. The path is decoded here as well, because the server
 * decodes it before routing: `/%61pi/` reaches the same endpoint as `/api/`. After decoding:
 *
 * - A path that starts with two slashes is refused as off-site. Copied into an address,
 *   `//host` names another site, however the link spelled it: `/.//host`, `/x/..//host`,
 *   `/%2e%2e//host`, `/./\host`, and this site's own origin followed by `//host`, all parse
 *   to that path.
 * - An empty segment, a dot segment, a backslash or a control character anywhere else is
 *   refused as invalid. The server writes none of them, and each makes one path read as another.
 * - An API endpoint is refused: it is never a page to open.
 */
function refusedPathError(pathname: string): string | null {
    let decoded: string;
    try {
        decoded = decodeURIComponent(pathname);
    } catch {
        return INVALID_LINK;
    }
    const slashed = decoded.replace(/\\/g, '/');
    if (slashed.startsWith('//')) {
        return OFF_SITE_LINK;
    }
    if (slashed !== decoded || /\/\/|\/\.{1,2}(?:\/|$)|[\u0000-\u001f\u007f]/.test(decoded)) {
        return INVALID_LINK;
    }
    if (/^\/api(?:\/|$)/i.test(decoded)) {
        return UNSUPPORTED_LINK;
    }
    return null;
}

/**
 * The absolute address `href` leads to from a page on `origin`, or null when it would leave it.
 *
 * Only a path from this site's root is accepted, and it is parsed the way the browser will
 * parse it, because a path is not safe on its own: written into an address, `//host/...` or
 * `/\host/...` names another site. Used when a classic target is built, and again by the
 * navigator immediately before it follows one.
 */
export function sameSiteAddress(href: string, origin: string): string | null {
    if (!href.startsWith('/')) {
        return null;
    }
    try {
        const url = new URL(href, origin);
        return url.origin === origin ? url.href : null;
    } catch {
        return null;
    }
}

function classic(href: string, notification: AppNotification, origin: string): ResolvedNotificationLink {
    if (!sameSiteAddress(href, origin)) {
        return { target: null, error: OFF_SITE_LINK };
    }
    return { target: { kind: 'classic', href, groupId: groupIdFor(notification) }, error: null };
}

/** The link's own path, query and fragment, as they are opened in the classic interface. */
function linkHref(url: URL): string {
    return `${url.pathname}${url.search}${url.hash}`;
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
        const runPath = unlinkedRunPath(notification);
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
    const refused = refusedPathError(url.pathname);
    if (refused) {
        return { target: null, error: refused };
    }

    // No empty segments are left to collapse, so only a trailing slash is set aside.
    const path = url.pathname.replace(/(.)\/$/, '$1');

    // A Microsoft 365 action waiting in a conversation is resolved on the classic chat page,
    // which is the only one that renders the pending-action card.
    if ((path === '/chats' || path === '/chat' || path === '/v2/chat') && url.searchParams.has('m365_pending_action')) {
        return classic(`/chats${url.search}${url.hash}`, notification, origin);
    }
    if (path === '/chats' || path === '/chat' || path === '/v2/chat') {
        return chatTarget(url);
    }

    if (looksLikeGroupDocument(url)) {
        return nativeGroupDocumentTarget(url, notification);
    }

    if (path === '/workflow-activity') {
        const runPath = workflowActivityRunPath(url, notification);
        return runPath ? route(runPath) : classic(linkHref(url), notification, origin);
    }

    if (path === '/approvals') {
        return classic(linkHref(url), notification, origin);
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

    return classic(linkHref(url), notification, origin);
}
