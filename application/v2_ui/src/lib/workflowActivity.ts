// workflowActivity.ts
// The Workflow Activity page's address, and the one set of rules every link to it follows.
//
// `/workflow-activity` shows one workflow run as a timeline. It takes the query string the classic
// page of the same name takes, so every link already in circulation -- a notice the server wrote, a
// Support shortcut, a classic bookmark -- maps to it one to one:
//
//   conversationId  the workflow's conversation; the latest run in it is shown
//   workflowId      the workflow
//   runId           one run
//   scope           `personal` (the default) or `group`
//   groupId         the group, for `scope=group`; the reader's active group when it is left out
//
// Any one of the three ids is enough to open the page. With none of them it shows its empty state.
//
// This is the only module that reads or builds that address, and it keeps its imports to types and
// one leaf module on purpose: the notification resolver and the Support shortcut translator both
// depend on it, and neither may pull the page's stores in with it. An identifier is checked on every
// read and every build, because an id is data a link carried, never a path this application wrote.

import { isWorkflowConversation, type BadgeSource } from './conversationBadges';
import type { WorkflowScope } from './workflowEditor';

/** The page's route, relative to the router's `/v2` base. */
export const WORKFLOW_ACTIVITY_PATH = '/workflow-activity';

export type WorkflowActivityScope = 'personal' | 'group';

export interface WorkflowActivityQuery {
    conversationId: string;
    workflowId: string;
    runId: string;
    scope: WorkflowActivityScope;
    /** Only ever set for the group scope. */
    groupId: string;
}

export type WorkflowActivityQueryRead =
    | { ok: true; query: WorkflowActivityQuery }
    | { ok: false; reason: string };

export const WORKFLOW_ACTIVITY_INVALID_LINK = 'This workflow activity link is not valid.';

/**
 * The run states that keep the page listening and keep Cancel run on offer.
 *
 * The same set the server's stream follows (`M365_ACTIVE_STATES` plus running and cancelling in
 * route_backend_workflows.py), and the classic page's `WORKFLOW_ACTIVE_STATUSES`. A run in any
 * other state is finished, or has not started, as far as this page is concerned.
 */
export const WORKFLOW_ACTIVITY_ACTIVE_STATUSES: ReadonlySet<string> = new Set([
    'running',
    'cancelling',
    'awaiting_approval',
    'awaiting_sharing_approval',
    'awaiting_analysis_approval',
    'awaiting_run_as_approval',
    'awaiting_sign_in',
    'ready_to_resume',
    'resuming',
]);

export function isWorkflowActivityActive(status: unknown): boolean {
    return WORKFLOW_ACTIVITY_ACTIVE_STATUSES.has(typeof status === 'string' ? status.trim().toLowerCase() : '');
}

const MAX_IDENTIFIER_LENGTH = 256;
const ID_FIELDS = ['conversationId', 'workflowId', 'runId', 'groupId'] as const;

/**
 * An id a link may carry: non-empty, not padded, not a dot segment, no separators a path or a
 * query would read as structure, and no control characters. The same rule the notification links
 * apply to the ids they carry (`requireWorkspaceId`), with the length the server keeps.
 */
export function isWorkflowActivityIdentifier(value: unknown): value is string {
    return (
        typeof value === 'string' &&
        value.length > 0 &&
        value.length <= MAX_IDENTIFIER_LENGTH &&
        value === value.trim() &&
        value !== '.' &&
        value !== '..' &&
        !/[/\\?#\u0000-\u001f\u007f]/.test(value)
    );
}

/** Whether the query names anything to show. */
export function hasWorkflowActivityIdentifier(query: Pick<WorkflowActivityQuery, 'conversationId' | 'workflowId' | 'runId'>): boolean {
    return Boolean(query.conversationId || query.workflowId || query.runId);
}

/**
 * Read the page's address.
 *
 * A parameter that is absent or empty names nothing. One that is present is checked, and the
 * whole link is refused when any is malformed rather than reading around it: a link with a bad id
 * in it is not one this application, or the classic one, ever wrote.
 */
export function readWorkflowActivityQuery(search: string | URLSearchParams): WorkflowActivityQueryRead {
    const params = typeof search === 'string' ? new URLSearchParams(search) : search;
    const ids: Record<(typeof ID_FIELDS)[number], string> = {
        conversationId: '',
        workflowId: '',
        runId: '',
        groupId: '',
    };
    for (const field of ID_FIELDS) {
        const value = params.get(field) ?? '';
        if (value === '') {
            continue;
        }
        if (!isWorkflowActivityIdentifier(value)) {
            return { ok: false, reason: WORKFLOW_ACTIVITY_INVALID_LINK };
        }
        ids[field] = value;
    }

    // Case and padding are forgiven in the scope, as the classic page forgives them, but a word
    // that is neither scope is not guessed at.
    const written = (params.get('scope') ?? '').trim().toLowerCase();
    if (written !== '' && written !== 'personal' && written !== 'group') {
        return { ok: false, reason: WORKFLOW_ACTIVITY_INVALID_LINK };
    }
    const scope: WorkflowActivityScope = written === 'group' ? 'group' : 'personal';
    return { ok: true, query: { ...ids, scope, groupId: scope === 'group' ? ids.groupId : '' } };
}

/** A stable key for the query, for effects that must restart when the page is pointed elsewhere. */
export function workflowActivityQueryKey(query: WorkflowActivityQuery): string {
    return JSON.stringify([query.scope, query.groupId, query.conversationId, query.workflowId, query.runId]);
}

/**
 * The page's route for a query, or null when any identifier is one a link must not carry.
 *
 * Written in one fixed order, and without `scope` for the default personal one, so the same
 * query always produces the same address. A group query carries `scope=group` and its group when
 * it has one.
 */
export function buildWorkflowActivityPath(
    query: Partial<WorkflowActivityQuery>,
    options: { requireIdentifier?: boolean } = {},
): string | null {
    const scope = query.scope === 'group' ? 'group' : 'personal';
    const values: Record<(typeof ID_FIELDS)[number], string> = {
        conversationId: query.conversationId ?? '',
        workflowId: query.workflowId ?? '',
        runId: query.runId ?? '',
        groupId: scope === 'group' ? query.groupId ?? '' : '',
    };
    for (const field of ID_FIELDS) {
        if (values[field] !== '' && !isWorkflowActivityIdentifier(values[field])) {
            return null;
        }
    }
    if (options.requireIdentifier && !hasWorkflowActivityIdentifier(values)) {
        return null;
    }

    const params = new URLSearchParams();
    for (const field of ['conversationId', 'workflowId', 'runId'] as const) {
        if (values[field]) {
            params.set(field, values[field]);
        }
    }
    if (scope === 'group') {
        params.set('scope', 'group');
        if (values.groupId) {
            params.set('groupId', values.groupId);
        }
    }
    const search = params.toString();
    return search ? `${WORKFLOW_ACTIVITY_PATH}?${search}` : WORKFLOW_ACTIVITY_PATH;
}

/**
 * The query string of a classic `/workflow-activity` link, exactly as written, when every id and
 * the scope in it can be carried to the V2 page; null when any cannot.
 *
 * Notification links keep their whole query. The classic page reads these five parameters and
 * so does the V2 page, so there is nothing to translate, only something to refuse.
 */
export function validatedWorkflowActivitySearch(search: string): string | null {
    return readWorkflowActivityQuery(search).ok ? search : null;
}

/**
 * Whether a router path is exactly what `buildWorkflowActivityPath` writes for a valid query.
 *
 * Support shortcuts reach the router only through an allowlist of paths this application wrote.
 * A path with a query cannot be listed, so it is accepted when it is the builder's own output
 * for ids that passed the same checks, and a path the link merely resembled is not.
 */
export function isWorkflowActivityRoute(path: string): boolean {
    if (path === WORKFLOW_ACTIVITY_PATH) {
        return true;
    }
    if (!path.startsWith(`${WORKFLOW_ACTIVITY_PATH}?`)) {
        return false;
    }
    const read = readWorkflowActivityQuery(path.slice(WORKFLOW_ACTIVITY_PATH.length + 1));
    return read.ok && buildWorkflowActivityPath(read.query) === path;
}

/* Where a person is sent from -------------------------------------------------------------- */

export interface WorkflowActivityTarget {
    scope?: WorkflowScope;
    conversationId?: unknown;
    workflowId?: unknown;
    runId?: unknown;
}

function text(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * The page for a run, a workflow or a conversation, from a workspace's own records, or null when
 * the record names none of them or names one a link cannot carry.
 *
 * A group workspace's link carries its group, so the page reads that group rather than whichever
 * one the reader last made active.
 */
export function workflowActivityHref(target: WorkflowActivityTarget): string | null {
    const scope = target.scope;
    const groupId = scope?.type === 'group' ? text(scope.groupId) : '';
    if (scope?.type === 'group' && !groupId) {
        return null;
    }
    return buildWorkflowActivityPath(
        {
            conversationId: text(target.conversationId),
            workflowId: text(target.workflowId),
            runId: text(target.runId),
            scope: scope?.type === 'group' ? 'group' : 'personal',
            groupId,
        },
        { requireIdentifier: true },
    );
}

/** The workspace a query reads, in the shape the workflow endpoints and the cancel call take. */
export function workflowActivityScope(query: WorkflowActivityQuery): WorkflowScope {
    return query.scope === 'group' ? { type: 'group', groupId: query.groupId } : { type: 'personal' };
}

function record(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** The workflow a conversation record says it came from: its own id, or the run's provenance. */
function conversationWorkflowId(source: Record<string, unknown>): string {
    return text(source.workflow_id) || text(record(source.workflow_provenance)?.workflow_id);
}

/**
 * The page for the conversation open in chat, or null when it is not a workflow's.
 *
 * What the classic chat decides (chat-conversation-info-button.js): a workflow conversation is
 * one whose `chat_type` is `workflow` or that names a workflow, and the button is offered while
 * personal workflows are on for the reader. A conversation a group workflow made says so on its
 * record, and opens the group's page when group workspaces are on; classic always asks for the
 * personal one. The sources are the metadata the chat loaded and the conversation's row in the
 * list, either of which may be missing.
 */
export function workflowConversationActivityHref(input: {
    conversationId: string | null;
    sources: ReadonlyArray<BadgeSource | null | undefined>;
    personalWorkflowsEnabled: boolean;
    groupWorkspacesEnabled: boolean;
}): string | null {
    const conversationId = text(input.conversationId);
    const sources = input.sources.map(record).filter((source): source is Record<string, unknown> => source !== null);
    if (!conversationId || !sources.some((source) => isWorkflowConversation(source as BadgeSource))) {
        return null;
    }
    const workflowId = sources.map(conversationWorkflowId).find(Boolean) ?? '';
    const groupId = sources
        .filter((source) => text(source.workspace_type).toLowerCase() === 'group')
        .map((source) => text(source.group_id))
        .find(Boolean);
    if (groupId) {
        return input.groupWorkspacesEnabled
            ? workflowActivityHref({ scope: { type: 'group', groupId }, conversationId, workflowId })
            : null;
    }
    return input.personalWorkflowsEnabled ? workflowActivityHref({ conversationId, workflowId }) : null;
}

/* The endpoints ------------------------------------------------------------------------------ */

/** The snapshot endpoint for a scope, or its server-sent event stream. */
export function workflowActivityApiPath(scope: WorkflowActivityScope, stream = false): string {
    const base = scope === 'group' ? '/api/group/workflows/activity' : '/api/user/workflows/activity';
    return stream ? `${base}/stream` : base;
}

/** The endpoint with the query the server reads: snake_case names, and the group only for a group. */
export function workflowActivityApiUrl(query: WorkflowActivityQuery, stream = false): string {
    const params = new URLSearchParams();
    if (query.conversationId) {
        params.set('conversation_id', query.conversationId);
    }
    if (query.workflowId) {
        params.set('workflow_id', query.workflowId);
    }
    if (query.runId) {
        params.set('run_id', query.runId);
    }
    if (query.scope === 'group' && query.groupId) {
        params.set('group_id', query.groupId);
    }
    const search = params.toString();
    const path = workflowActivityApiPath(query.scope, stream);
    return search ? `${path}?${search}` : path;
}

/* What a failed read says -------------------------------------------------------------------- */

const GENERIC_FAILURE = /^Request failed with status \d+$/;

const FAILURE_FALLBACKS: Readonly<Record<number, string>> = {
    400: 'This workflow activity could not be opened.',
    403: 'You do not have access to this workflow activity.',
    404: 'This workflow activity was not found.',
};

export const WORKFLOW_ACTIVITY_SERVER_ERROR = 'Unable to load workflow activity right now.';
export const WORKFLOW_ACTIVITY_OFFLINE_ERROR = 'Unable to load workflow activity. Check your connection and try again.';

/**
 * A failed call as a sentence for the page; `fallback` is what the page says for its own call
 * when the server said nothing useful.
 *
 * The server says why in its own words -- a disabled feature, a missing role, a run that is not
 * there -- and those are what a person needs. A refused role arrives with the sentence under
 * `message` and only the word "Forbidden" under `error`, so for a 403 the sentence wins. When the
 * server said nothing useful the status picks a fallback. No status at all is a call that never
 * got an answer, whose own message is the browser's wording and is not shown. A body that was not
 * JSON -- a gateway's error page, an empty body -- is not the server's sentence either, so it is
 * never shown: the API client keeps its text as the message and as a string payload. Duck-typed on
 * `status` and `payload` so this module needs no import of the API client.
 */
export function describeWorkflowActivityFailure(error: unknown, fallback?: string): string {
    const failure = record(error);
    const status = typeof failure?.status === 'number' ? failure.status : 0;
    if (!status) {
        return fallback ?? WORKFLOW_ACTIVITY_OFFLINE_ERROR;
    }
    const body = record(failure?.payload);
    if (!body) {
        return fallback ?? FAILURE_FALLBACKS[status] ?? WORKFLOW_ACTIVITY_SERVER_ERROR;
    }
    const sentence = text(body.message);
    if (status === 403 && sentence) {
        return sentence;
    }
    const message = text(failure?.message);
    if (message && !GENERIC_FAILURE.test(message)) {
        return message;
    }
    return fallback ?? FAILURE_FALLBACKS[status] ?? WORKFLOW_ACTIVITY_SERVER_ERROR;
}
