// workflowAssist.ts
// The Ask AI tab's side of POST /api/user/workflows/assist: the request it sends, the answer it
// accepts, and what a failure means for the reader.
//
// Everything the server sends back is untrusted. The answer is checked field by field, the
// candidate is diffed here rather than trusting the change list that came with it, and every
// string is plain text for the UI to render as a text node.

import { api, apiUrl, ApiError, CREDENTIALS_MODE } from './apiClient';
import type { ContextItem } from './chatContext';
import { codePointLength, codePointPrefix } from './codePoints';
import { canonicalPlanReferences, planDraftReferences, PlanReferenceError, type PlanReference } from './planReferences';
import { diffWorkflowChanges, type WorkflowChange, type WorkflowChangeTarget } from './workflowChangeTracking';
import { WORKFLOW_TASK_INSTRUCTIONS_LIMIT, type WorkflowDefinition } from './workflowEditor';
import { isFlowRegion } from './workflowFlow';
import { isRecord, sameEditorValue } from './workspaceAuthoring';

export const WORKFLOW_ASSIST_PATH = '/api/user/workflows/assist';
export const WORKFLOW_DRAFT_INSTRUCTIONS_PATH = '/api/workflows/draft-instructions';
/** The server counts the instruction in code points, after its raw-text check. */
export const WORKFLOW_ASSIST_INSTRUCTION_LIMIT = 2000;
export const WORKFLOW_ASSIST_TURN_TEXT_LIMIT = 4000;
/** Conversation items: ten whole exchanges, so a replay never starts with an orphan reply. */
export const WORKFLOW_ASSIST_MAX_TURNS = 20;
export const WORKFLOW_ASSIST_REFERENCE_LIMIT = 20;
export const WORKFLOW_ASSIST_REPLY_LIMIT = 1500;
/** The server stops at about 150 seconds; the browser waits a little longer for its answer. */
export const WORKFLOW_ASSIST_DEADLINE_MS = 170_000;

const IDENTIFIER_LIMIT = 256;
const TIME_ZONE_LIMIT = 64;
const MAX_DEPTH = 200;
const REPLAY_LABELS = 12;
const REPLAY_LABEL_LIMIT = 120;
const SERVER_TEXT_LIMIT = 1000;
const CHANGE_TEXT_LIMIT = 300;
const CONTEXT_DOCUMENT_LIMIT = 200;
const MAX_REPORTED_CHANGES = 500;
const MAX_WARNINGS = 50;
const MAX_RETRY_AFTER_SECONDS = 3600;

// The characters the server refuses in text. Tab, LF and CR are allowed.
const CONTROL_CHARACTERS = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;

export const UNREADABLE_ANSWER_MESSAGE = "The assistant's answer couldn't be read. Nothing was changed.";
export const STALE_DRAFT_MESSAGE = 'Nothing was applied because the draft changed while Ask AI was working. Send it again to use the current draft.';
export const TAGS_UNSUPPORTED_MESSAGE = 'Workflows use documents, not tags. Remove the tag and pick documents instead.';
export const WORKSPACE_REFERENCE_MESSAGE = 'Ask AI can use documents, not whole workspaces. Remove the workspace and pick documents instead.';
export const REFERENCE_LIMIT_MESSAGE = `Attach at most ${WORKFLOW_ASSIST_REFERENCE_LIMIT} documents.`;
export const REFERENCE_PICKER_MESSAGE = 'Choose documents from the # picker.';
export const MISSING_REVISION_MESSAGE = 'Reload the workflow to use Ask AI.';

export type WorkflowAssistOutcome = 'changed' | 'explained' | 'question';

export interface WorkflowAssistBase {
    readonly workflow_id: string;
    readonly definition_revision: string;
}

export interface WorkflowAssistConversationItem {
    readonly role: 'user' | 'assistant';
    readonly text: string;
}

export interface WorkflowAssistRequest {
    readonly submission_id: string;
    readonly base: WorkflowAssistBase | null;
    readonly instruction: string;
    readonly conversation: readonly WorkflowAssistConversationItem[];
    readonly focus: string | null;
    readonly time_zone?: string;
    readonly draft: WorkflowDefinition;
    readonly references: readonly PlanReference[];
}

export type WorkflowAssistRequestErrorCode = 'invalid_request' | 'reference_limit' | 'tags_unsupported';

/** A request the browser refuses to send, with a message to show instead. */
export class WorkflowAssistRequestError extends Error {
    readonly code: WorkflowAssistRequestErrorCode;

    constructor(message: string, code: WorkflowAssistRequestErrorCode = 'invalid_request') {
        super(message);
        this.name = 'WorkflowAssistRequestError';
        this.code = code;
    }
}

/** How a completed turn stands now, for the conversation the next request replays. */
export type WorkflowAssistReplayState =
    | 'none' | 'applied' | 'partly_undone' | 'undone' | 'pending' | 'declined' | 'earlier';

export interface WorkflowAssistReplayTurn {
    readonly instruction: string;
    readonly reply: string;
    readonly state: WorkflowAssistReplayState;
    /** What the turn changed, worded for the reader. */
    readonly changes: readonly string[];
}

/** Text the server accepts: no control characters except tab, LF and CR, and no lone surrogate. */
export function workflowAssistText(value: string): string {
    return value.replace(CONTROL_CHARACTERS, '').replace(LONE_SURROGATE, '\ufffd');
}

function clipped(value: string, limit: number): string {
    const text = value.replace(/\s+/g, ' ').trim();
    return codePointLength(text) > limit ? `${codePointPrefix(text, limit - 1).trimEnd()}…` : text;
}

function replaySuffix(turn: WorkflowAssistReplayTurn): string {
    const labels = turn.changes.map((label) => clipped(workflowAssistText(label), REPLAY_LABEL_LIMIT)).filter(Boolean);
    const shown = labels.slice(0, REPLAY_LABELS);
    const more = labels.length - shown.length;
    const list = shown.length ? `: ${shown.join('; ')}${more > 0 ? `; and ${more} more` : ''}.` : '.';
    switch (turn.state) {
        case 'applied':
            return `Changes applied${list}`;
        case 'partly_undone':
            return `Changes applied${list} The user later undid some of them.`;
        case 'undone':
            return `These changes were applied and later undone${list}`;
        case 'pending':
            return `These changes are waiting for the user's confirmation and are not applied yet${list}`;
        case 'declined':
            return 'No changes were applied.';
        case 'earlier':
            return `These changes were made in an earlier editing session and may not have been saved${list}`;
        default:
            return '';
    }
}

function replayItem(role: 'user' | 'assistant', text: string, suffix = ''): WorkflowAssistConversationItem | null {
    const body = workflowAssistText(text).trim();
    const combined = suffix ? (body ? `${body}\n\n${suffix}` : suffix) : body;
    const capped = codePointPrefix(combined, WORKFLOW_ASSIST_TURN_TEXT_LIMIT);
    return capped.trim() ? { role, text: capped } : null;
}

/**
 * The conversation a request replays: the last ten completed exchanges, oldest first.
 *
 * Only completed turns belong here; a failed or cancelled one never reaches this function. An
 * assistant item is its reply plus what became of its changes, so the model knows what the draft
 * it is sent already holds.
 */
export function workflowAssistConversation(
    turns: readonly WorkflowAssistReplayTurn[],
): WorkflowAssistConversationItem[] {
    const items: WorkflowAssistConversationItem[] = [];
    for (const turn of turns.slice(-(WORKFLOW_ASSIST_MAX_TURNS / 2))) {
        const user = replayItem('user', turn.instruction);
        const assistant = replayItem('assistant', turn.reply, replaySuffix(turn));
        if (user) items.push(user);
        if (assistant) items.push(assistant);
    }
    return items.slice(-WORKFLOW_ASSIST_MAX_TURNS);
}

/**
 * The `#` documents a request carries. Nothing is dropped silently: a tag, a whole workspace or
 * too many documents is refused with a message.
 */
export function workflowAssistReferences(draft: { contextItems: readonly ContextItem[] }): PlanReference[] {
    if (draft.contextItems.some((item) => item.kind === 'tag')) {
        throw new WorkflowAssistRequestError(TAGS_UNSUPPORTED_MESSAGE, 'tags_unsupported');
    }
    if (draft.contextItems.some((item) => item.kind !== 'document')) {
        throw new WorkflowAssistRequestError(WORKSPACE_REFERENCE_MESSAGE);
    }
    try {
        return canonicalPlanReferences(planDraftReferences(draft), WORKFLOW_ASSIST_REFERENCE_LIMIT);
    } catch (problem) {
        if (problem instanceof PlanReferenceError) {
            throw new WorkflowAssistRequestError(
                problem.code === 'reference_limit' ? REFERENCE_LIMIT_MESSAGE : REFERENCE_PICKER_MESSAGE,
                problem.code,
            );
        }
        throw problem;
    }
}

/** Every flow block id in a structured draft, nested regions included. */
export function workflowFlowNodeIds(draft: WorkflowDefinition): Set<string> {
    const ids = new Set<string>();
    const walk = (region: unknown, depth: number) => {
        if (!isRecord(region) || !Array.isArray(region.nodes) || depth > 32) return;
        for (const node of region.nodes) {
            if (!isRecord(node)) continue;
            if (typeof node.id === 'string' && node.id) ids.add(node.id);
            for (const child of [node.then, node.else, node.body]) walk(child, depth + 1);
        }
    };
    if (isFlowRegion(draft.flow)) walk(draft.flow, 0);
    return ids;
}

/** Whether `focus` still names a task, or a flow block of a structured draft. */
export function workflowAssistFocusValid(draft: WorkflowDefinition, focus: string | null): focus is string {
    if (!focus) return false;
    if (draft.tasks.some((task) => task.id === focus)) return true;
    return draft.definition_version === 3 && workflowFlowNodeIds(draft).has(focus);
}

function validIdentifier(value: unknown): value is string {
    return typeof value === 'string' && Boolean(value.trim()) && value.length <= IDENTIFIER_LIMIT
        && !/[\x00-\x1f\x7f]/.test(value);
}

/** The browser's IANA time zone, or null when it has none. */
export function browserTimeZone(): string | null {
    try {
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        return typeof zone === 'string' && zone ? zone : null;
    } catch {
        return null;
    }
}

export interface WorkflowAssistRequestInput {
    readonly submissionId: string;
    readonly instruction: string;
    /** The version the editor opened or last saved; its id decides whether there is a base. */
    readonly baseline: WorkflowDefinition;
    /** The session's current draft, the same object the answer is later compared with. */
    readonly draft: WorkflowDefinition;
    readonly contextItems: readonly ContextItem[];
    readonly conversation: readonly WorkflowAssistReplayTurn[];
    readonly focus: string | null;
    readonly timeZone: string | null;
    /** The schedule editor's time zone names; the zone is sent only when it is one of them. */
    readonly timeZones: ReadonlySet<string> | null;
}

/** Build 3b's request exactly. Throws `WorkflowAssistRequestError` for a request it would refuse. */
export function buildWorkflowAssistRequest(input: WorkflowAssistRequestInput): WorkflowAssistRequest {
    // The server refuses control characters rather than dropping them, so they go here.
    const instruction = workflowAssistText(input.instruction).trim();
    if (!instruction) {
        throw new WorkflowAssistRequestError('Type what you want the assistant to do, then send it.');
    }
    if (codePointLength(instruction) > WORKFLOW_ASSIST_INSTRUCTION_LIMIT) {
        throw new WorkflowAssistRequestError(
            `Shorten the message to ${WORKFLOW_ASSIST_INSTRUCTION_LIMIT.toLocaleString()} characters or fewer.`,
        );
    }
    const references = workflowAssistReferences({ contextItems: input.contextItems });
    const workflowId = input.baseline.id;
    let base: WorkflowAssistBase | null = null;
    if (workflowId) {
        const revision = input.baseline.definition_revision;
        if (!validIdentifier(workflowId) || !validIdentifier(revision)) {
            throw new WorkflowAssistRequestError(MISSING_REVISION_MESSAGE);
        }
        base = { workflow_id: workflowId, definition_revision: revision };
    } else if (input.draft.id) {
        // A new or proposal draft has no saved workflow behind it, so it must not claim one.
        throw new WorkflowAssistRequestError(MISSING_REVISION_MESSAGE);
    }
    const zone = input.timeZone;
    const sendZone = Boolean(zone && zone.length <= TIME_ZONE_LIMIT && input.timeZones?.has(zone));
    return {
        submission_id: input.submissionId,
        base,
        instruction,
        conversation: workflowAssistConversation(input.conversation),
        focus: workflowAssistFocusValid(input.draft, input.focus) ? input.focus : null,
        ...(sendZone && zone ? { time_zone: zone } : {}),
        draft: input.draft,
        references,
    };
}

// ---------------------------------------------------------------------------------------------
// The answer
// ---------------------------------------------------------------------------------------------

export interface WorkflowAssistReportedChange {
    readonly key: string;
    readonly label: string;
    readonly ownerLabel: string;
    readonly summary: string;
    readonly focusKey: string;
    readonly nodeId?: string;
}

export interface WorkflowAssistWarning {
    readonly code: string;
    readonly message: string;
    readonly focusKey?: string;
    readonly nodeId?: string;
}

export interface WorkflowAssistResponse {
    readonly submissionId: string;
    readonly outcome: WorkflowAssistOutcome;
    readonly reply: string;
    readonly candidate: WorkflowDefinition | null;
    readonly changes: readonly WorkflowAssistReportedChange[];
    readonly warnings: readonly WorkflowAssistWarning[];
    readonly contextDocuments: readonly string[];
}

function serverText(value: unknown, limit: number): string | null {
    return typeof value === 'string' ? clipped(workflowAssistText(value), limit) : null;
}

function reportedTarget(value: unknown): { focusKey: string; nodeId?: string } | null {
    if (!isRecord(value) || typeof value.focus_key !== 'string' || !value.focus_key
        || value.focus_key.length > 1024) return null;
    const nodeId = typeof value.node_id === 'string' && value.node_id && value.node_id.length <= IDENTIFIER_LIMIT
        ? value.node_id : undefined;
    return { focusKey: value.focus_key, ...(nodeId ? { nodeId } : {}) };
}

function reportedChange(value: unknown): WorkflowAssistReportedChange | null {
    if (!isRecord(value) || typeof value.key !== 'string' || !value.key || value.key.length > 1024) return null;
    const target = reportedTarget(value.target);
    const label = serverText(value.label, CHANGE_TEXT_LIMIT);
    const ownerLabel = serverText(value.owner_label, CHANGE_TEXT_LIMIT);
    const summary = serverText(value.summary, CHANGE_TEXT_LIMIT);
    if (!target || label === null || ownerLabel === null || summary === null) return null;
    return { key: value.key, label, ownerLabel, summary, ...target };
}

function reportedWarning(value: unknown): WorkflowAssistWarning | null {
    if (!isRecord(value) || typeof value.code !== 'string' || !/^[a-z0-9_]{1,64}$/.test(value.code)) return null;
    const message = serverText(value.message, SERVER_TEXT_LIMIT);
    if (!message) return null;
    const target = value.target === undefined || value.target === null ? null : reportedTarget(value.target);
    return { code: value.code, message, ...(target ?? {}) };
}

/**
 * Check a 200 answer. Returns null for anything that is not exactly the contract: the wrong
 * submission id, an unknown outcome, or a candidate present when the outcome is not `changed` (or
 * missing when it is). Malformed change, warning and document entries are dropped, because they
 * are display hints; the change list shown is re-derived from the candidate anyway.
 */
export function parseWorkflowAssistResponse(value: unknown, submissionId: string): WorkflowAssistResponse | null {
    if (!isRecord(value) || value.submission_id !== submissionId) return null;
    const outcome = value.outcome;
    if (outcome !== 'changed' && outcome !== 'explained' && outcome !== 'question') return null;
    if (typeof value.reply !== 'string') return null;
    const candidate = value.candidate;
    if (outcome === 'changed') {
        if (!isRecord(candidate) || !Array.isArray(candidate.tasks)) return null;
    } else if (candidate !== null && candidate !== undefined) {
        return null;
    }
    if (!Array.isArray(value.changes) || !Array.isArray(value.warnings) || !Array.isArray(value.context_documents)) {
        return null;
    }
    const reply = workflowAssistText(value.reply).trim();
    return {
        submissionId,
        outcome,
        reply: codePointLength(reply) > WORKFLOW_ASSIST_REPLY_LIMIT
            ? `${codePointPrefix(reply, WORKFLOW_ASSIST_REPLY_LIMIT - 1)}…` : reply,
        candidate: outcome === 'changed' ? candidate as WorkflowDefinition : null,
        changes: value.changes.slice(0, MAX_REPORTED_CHANGES).map(reportedChange)
            .filter((change): change is WorkflowAssistReportedChange => change !== null),
        warnings: value.warnings.slice(0, MAX_WARNINGS).map(reportedWarning)
            .filter((warning): warning is WorkflowAssistWarning => warning !== null),
        contextDocuments: value.context_documents.slice(0, WORKFLOW_ASSIST_REFERENCE_LIMIT)
            .map((label) => serverText(label, CONTEXT_DOCUMENT_LIMIT))
            .filter((label): label is string => Boolean(label)),
    };
}

// ---------------------------------------------------------------------------------------------
// Failures
// ---------------------------------------------------------------------------------------------

export interface WorkflowAssistFailure {
    readonly status: number;
    readonly code: string;
    readonly message: string;
    /** Wait this long before sending again: a 429, or a throttled 503. */
    readonly retryAfterSeconds: number | null;
    /** The saved workflow changed after the editor opened; reloading it lets Ask AI work again. */
    readonly reload: boolean;
}

const STATUS_FALLBACKS: Readonly<Record<number, string>> = {
    400: "The assistant couldn't use this request. Nothing was changed.",
    401: 'Your session expired. Sign in again to use Ask AI.',
    403: "Ask AI isn't available to you right now.",
    404: "This workflow couldn't be found. It may have been deleted.",
    409: 'The saved workflow changed after the editor opened. Your draft was kept. Reload the workflow to use the assistant.',
    413: 'This request is too large for the assistant. Ask for a smaller change, or start a new thread.',
    429: 'The assistant is busy. Wait a moment, then try again.',
    500: 'The assistant failed. Nothing was changed. Try again.',
    502: "The assistant's answer couldn't be used. Nothing was changed. Try again.",
    503: 'The assistant is unavailable right now. Nothing was changed. Try again later.',
};

function clampRetryAfter(seconds: number): number {
    return Math.min(MAX_RETRY_AFTER_SECONDS, Math.max(1, Math.ceil(seconds)));
}

/** Seconds to wait, from a `Retry-After` header (seconds or an HTTP date), or else the body. */
export function workflowAssistRetryAfter(header: string | null, body: unknown, now = Date.now()): number | null {
    const text = (header ?? '').trim();
    if (/^\d{1,10}$/.test(text)) return clampRetryAfter(Number(text));
    if (text) {
        const date = Date.parse(text);
        if (!Number.isNaN(date)) return clampRetryAfter((date - now) / 1000);
    }
    const seconds = isRecord(body) ? body.retry_after_seconds : undefined;
    return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0 ? clampRetryAfter(seconds) : null;
}

/**
 * What a failed request means for the reader. The server's `error` is a safe template (the rate
 * limit's is an admin's text, possibly Markdown); it is shown as plain text either way.
 */
export function describeWorkflowAssistError(status: number, body: unknown, retryAfterHeader: string | null = null): WorkflowAssistFailure {
    const code = isRecord(body) && typeof body.code === 'string' && /^[a-z0-9_]{1,64}$/.test(body.code) ? body.code : '';
    const fallback = STATUS_FALLBACKS[status] ?? `The assistant request failed (status ${status}). Nothing was changed.`;
    let message = (isRecord(body) ? serverText(body.error, SERVER_TEXT_LIMIT) : null) || fallback;
    if (code === 'workflow_deleted') message = `${message} Your draft is still in the editor.`;
    const retryAfterSeconds = status === 429 || status === 503 ? workflowAssistRetryAfter(retryAfterHeader, body) : null;
    return {
        status,
        code,
        message,
        retryAfterSeconds: status === 429 && retryAfterSeconds === null ? 1 : retryAfterSeconds,
        reload: status === 409 && code === 'workflow_definition_conflict',
    };
}

export type WorkflowAssistPostResult =
    | { readonly ok: true; readonly response: WorkflowAssistResponse }
    | { readonly ok: false; readonly aborted: true }
    | { readonly ok: false; readonly aborted?: false; readonly failure: WorkflowAssistFailure };

/**
 * POST one turn. A cancel through `signal` is `aborted`; the browser deadline and a lost
 * connection are failures the reader can retry.
 */
export async function postWorkflowAssist(
    body: WorkflowAssistRequest,
    signal: AbortSignal,
    deadlineMs = WORKFLOW_ASSIST_DEADLINE_MS,
): Promise<WorkflowAssistPostResult> {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, deadlineMs);
    const stop = () => controller.abort();
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', stop, { once: true });
    try {
        // A raw fetch rather than apiClient: ApiError drops the headers, and a throttled 503 carries
        // its wait only in Retry-After.
        const response = await fetch(apiUrl(WORKFLOW_ASSIST_PATH), {
            method: 'POST',
            credentials: CREDENTIALS_MODE,
            signal: controller.signal,
            headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const text = await response.text();
        let payload: unknown = null;
        try {
            payload = text ? JSON.parse(text) : null;
        } catch {
            payload = null;
        }
        if (signal.aborted) return { ok: false, aborted: true };
        if (!response.ok) {
            return { ok: false, failure: describeWorkflowAssistError(response.status, payload, response.headers.get('Retry-After')) };
        }
        const parsed = parseWorkflowAssistResponse(payload, body.submission_id);
        return parsed ? { ok: true, response: parsed } : {
            ok: false,
            failure: { status: response.status, code: 'unreadable', message: UNREADABLE_ANSWER_MESSAGE, retryAfterSeconds: null, reload: false },
        };
    } catch {
        if (signal.aborted) return { ok: false, aborted: true };
        return {
            ok: false,
            failure: timedOut ? {
                status: 0, code: 'browser_timeout', retryAfterSeconds: null, reload: false,
                message: 'The assistant took too long to answer. Nothing was changed. Try again, or ask for a smaller change.',
            } : {
                status: 0, code: 'network_error', retryAfterSeconds: null, reload: false,
                message: "Couldn't reach the assistant. Nothing was changed. Check your connection and try again.",
            },
        };
    } finally {
        clearTimeout(timer);
        signal.removeEventListener('abort', stop);
    }
}

// ---------------------------------------------------------------------------------------------
// Applying the candidate
// ---------------------------------------------------------------------------------------------

/**
 * Whether a live value and a value that went through JSON hold the same JSON. JSON drops
 * `undefined` object keys and turns `undefined` array items and non-finite numbers into null.
 */
export function jsonEquivalent(live: unknown, json: unknown, depth = 0): boolean {
    if (Object.is(live, json)) return true;
    if (depth > MAX_DEPTH) return false;
    if (live === undefined || typeof live === 'function' || typeof live === 'symbol') return json === null || json === undefined;
    if (typeof live === 'number') return Number.isFinite(live) ? live === json : json === null;
    if (Array.isArray(live)) {
        return Array.isArray(json) && live.length === json.length
            && live.every((item, index) => jsonEquivalent(item, json[index], depth + 1));
    }
    if (isRecord(live)) {
        if (!isRecord(json)) return false;
        const liveKeys = Object.keys(live).filter((key) => live[key] !== undefined && typeof live[key] !== 'function');
        return liveKeys.length === Object.keys(json).length
            && liveKeys.every((key) => Object.hasOwn(json, key) && jsonEquivalent(live[key], json[key], depth + 1));
    }
    return false;
}

function uniqueIds(items: readonly unknown[]): Map<string, unknown> | null {
    const byId = new Map<string, unknown>();
    for (const item of items) {
        if (!isRecord(item) || typeof item.id !== 'string' || !item.id || byId.has(item.id)) return null;
        byId.set(item.id, item);
    }
    return byId;
}

function setOwn(record: Record<string, unknown>, key: string, value: unknown) {
    Object.defineProperty(record, key, { value, enumerable: true, writable: true, configurable: true });
}

function rebase(live: unknown, candidate: unknown, depth: number): unknown {
    if (jsonEquivalent(live, candidate)) return live;
    if (depth > MAX_DEPTH) return candidate;
    if (Array.isArray(live) && Array.isArray(candidate)) {
        const liveById = uniqueIds(live);
        if (liveById && uniqueIds(candidate)) {
            return candidate.map((item) => {
                const match = isRecord(item) ? liveById.get(item.id as string) : undefined;
                return match === undefined ? item : rebase(match, item, depth + 1);
            });
        }
        return candidate.map((item, index) => index < live.length ? rebase(live[index], item, depth + 1) : item);
    }
    if (isRecord(live) && isRecord(candidate)) {
        const result: Record<string, unknown> = {};
        for (const key of Object.keys(live)) {
            if (Object.hasOwn(candidate, key)) setOwn(result, key, rebase(live[key], candidate[key], depth + 1));
            // JSON dropped an undefined key on the way out; it was not removed.
            else if (live[key] === undefined) setOwn(result, key, undefined);
        }
        for (const key of Object.keys(candidate)) {
            if (!Object.hasOwn(live, key)) setOwn(result, key, candidate[key]);
        }
        return result;
    }
    return candidate;
}

/**
 * The candidate laid over the live draft: wherever the candidate holds the JSON the editor sent,
 * the live value (and its identity) is kept, so `undefined` keys and untouched subtrees survive the
 * round trip. Array items are matched by a unique `id`, otherwise by position.
 */
export function rebaseAssistCandidate(live: WorkflowDefinition, candidate: WorkflowDefinition): WorkflowDefinition {
    return rebase(live, candidate, 0) as WorkflowDefinition;
}

/** Whether the live draft is still the one a turn was sent with. */
export function assistDraftUnchanged(sent: WorkflowDefinition, live: WorkflowDefinition): boolean {
    return sent === live || sameEditorValue(sent, live);
}

export interface WorkflowAssistVerifiedChange {
    readonly key: string;
    readonly summary: string;
    /** The server reported this key too. */
    readonly reported: boolean;
    /** The editor's own change, with the target Jump to uses. */
    readonly change: WorkflowChange;
}

export interface WorkflowAssistVerification {
    readonly changes: readonly WorkflowAssistVerifiedChange[];
    /** Keys the server reported that the editor's diff did not produce; never shown. */
    readonly unverified: readonly string[];
}

/** A change worded the way the server words it: "<added item>: <owner>", or "<owner>: <field>". */
export function workflowAssistChangeSummary(change: WorkflowChange): string {
    if (change.kind === 'added' || change.kind === 'removed') return `${change.label}: ${change.ownerLabel}`;
    return `${change.ownerLabel}: ${change.label}`;
}

/**
 * What a turn changed, decided by the editor's own diff of the draft it sent against the rebased
 * candidate. The server's wording and flow block are used only for keys the diff also produced.
 */
export function verifyAssistChanges(
    sent: WorkflowDefinition,
    rebased: WorkflowDefinition,
    reported: readonly WorkflowAssistReportedChange[],
): WorkflowAssistVerification {
    const diff = diffWorkflowChanges(sent, rebased);
    const byKey = new Map(reported.map((change) => [change.key, change]));
    const nodes = workflowFlowNodeIds(rebased);
    const changes = diff.changes.map((change) => {
        const report = byKey.get(change.key);
        const nodeId = report?.nodeId && nodes.has(report.nodeId) ? report.nodeId : change.target.nodeId;
        const target: WorkflowChangeTarget = { focusKey: change.target.focusKey, ...(nodeId ? { nodeId } : {}) };
        return {
            key: change.key,
            summary: report?.summary || workflowAssistChangeSummary(change),
            reported: Boolean(report),
            change: { ...change, target },
        };
    });
    return { changes, unverified: reported.filter((change) => !diff.byKey.has(change.key)).map((change) => change.key) };
}

// ---------------------------------------------------------------------------------------------
// Turns
// ---------------------------------------------------------------------------------------------

const TURN_LABEL_LIMIT = 80;

/** A turn's history label, such as "Ask AI: add a schedule", short enough for the Changes tab. */
export function workflowAssistTurnLabel(prefix: string, text: string): string {
    const body = clipped(workflowAssistText(text), TURN_LABEL_LIMIT);
    return body ? `${prefix}: ${body}` : prefix;
}

/** What the editor did with a turn's candidate. `none`: the turn had nothing to apply. */
export type WorkflowAssistApply = 'applied' | 'pending' | 'rejected' | 'noop' | 'none';

/** The authoring session's `revertTurn` answer, as a turn's card reports it. */
export type WorkflowAssistUndoResult =
    | { readonly status: 'unavailable' | 'noop' }
    | { readonly status: 'rejected'; readonly message: string }
    | {
        readonly status: 'applied' | 'confirmation_required';
        readonly reverted: number;
        readonly skipped: number;
        readonly revertedKeys: readonly { key: string; label: string }[];
        readonly skippedKeys: readonly { key: string; label: string; reason?: string }[];
    };

/** What one completed turn's card shows. The thread keeps the messages; this keeps the rest. */
export interface WorkflowAssistTurnRecord {
    readonly threadKey: string;
    /** The editing session the turn was answered in: the identity of the version the editor opened. */
    readonly epoch: string;
    readonly instruction: string;
    readonly outcome: WorkflowAssistOutcome;
    readonly reply: string;
    /** The editor's own diff of the draft it sent against the candidate. */
    readonly changes: readonly WorkflowAssistVerifiedChange[];
    readonly warnings: readonly WorkflowAssistWarning[];
    readonly contextDocuments: readonly string[];
    readonly apply: WorkflowAssistApply;
    /** Why the editor refused the candidate, with `apply: 'rejected'`. */
    readonly applyMessage?: string;
    /** What the latest Undo did. */
    readonly undo?: WorkflowAssistUndoResult;
    /** Counts Undo presses, so the card can move focus to each new result. */
    readonly undoSequence: number;
}

/** The parts of the authoring session a turn's state is read from. */
export interface WorkflowAssistHistoryView {
    readonly steps: readonly { readonly origin: string; readonly turnId?: string; readonly applied: boolean }[];
    readonly attribution: ReadonlyMap<string, { readonly turnId?: string }>;
    readonly pending: { readonly kind: string; readonly action?: { readonly origin?: string; readonly turnId?: string } } | null;
}

/**
 * Where a completed turn's changes stand now, read from the authoring history rather than
 * remembered, so Undo, Redo and a per-field revert are all reflected.
 */
export function workflowAssistTurnState(
    turnId: string,
    record: WorkflowAssistTurnRecord | undefined,
    view: WorkflowAssistHistoryView,
    epoch: string,
): WorkflowAssistReplayState {
    if (!record || record.outcome !== 'changed' || !record.changes.length
        || record.apply === 'none' || record.apply === 'noop') {
        return 'none';
    }
    if (record.epoch !== epoch) return 'earlier';
    const action = view.pending?.action;
    if (action?.origin === 'ai' && action.turnId === turnId) return 'pending';
    if (record.apply === 'rejected') return 'declined';
    let seen = false;
    let latest: { readonly origin: string } | null = null;
    for (const step of view.steps) {
        if (step.turnId !== turnId) continue;
        seen = true;
        if (step.applied) latest = step;
    }
    if (latest) {
        if (latest.origin === 'ai') return 'applied';
        const undo = record.undo;
        return undo && (undo.status === 'applied' || undo.status === 'confirmation_required') && undo.skipped > 0
            ? 'partly_undone' : 'undone';
    }
    if (seen) return 'undone';
    // The history dropped the turn's step; the attribution still knows what it wrote.
    for (const stamp of view.attribution.values()) {
        if (stamp.turnId === turnId) return 'applied';
    }
    return record.apply === 'applied' ? 'undone' : 'declined';
}

/** A thread exchange, as much of it as a replay reads. */
export interface WorkflowAssistReplayExchange {
    readonly id: string;
    readonly status: string;
    readonly text: string;
    readonly reply?: string;
}

/**
 * The completed turns a request replays, oldest first. Failed, cancelled and pending exchanges
 * never reach the server, and neither does the exchange being sent.
 */
export function workflowAssistReplay(
    exchanges: readonly WorkflowAssistReplayExchange[],
    records: (turnId: string) => WorkflowAssistTurnRecord | undefined,
    view: WorkflowAssistHistoryView,
    epoch: string,
    excludeId?: string,
): WorkflowAssistReplayTurn[] {
    const turns: WorkflowAssistReplayTurn[] = [];
    for (const exchange of exchanges) {
        if (exchange.status !== 'done' || exchange.id === excludeId) continue;
        const record = records(exchange.id);
        const state = workflowAssistTurnState(exchange.id, record, view, epoch);
        turns.push({
            instruction: record?.instruction ?? exchange.text,
            reply: record?.reply ?? exchange.reply ?? '',
            state,
            changes: state === 'none' || state === 'declined' || !record ? [] : record.changes.map((change) => change.summary),
        });
    }
    return turns;
}

// ---------------------------------------------------------------------------------------------
// Draft with AI
// ---------------------------------------------------------------------------------------------

/** The draft with one empty task's instructions filled in, or null when the task is gone or no longer empty. */
export function withDraftedInstructions(draft: WorkflowDefinition, taskId: string, instructions: string): WorkflowDefinition | null {
    const task = draft.tasks.find((item) => item.id === taskId);
    if (!task || task.instructions.trim()) return null;
    return { ...draft, tasks: draft.tasks.map((item) => item.id === taskId ? { ...item, instructions } : item) };
}

/** Ask the draft-instructions route for one task's instructions. Throws an Error with a plain-text message. */
export async function requestDraftInstructions(
    workflow: WorkflowDefinition,
    taskName: string,
    signal: AbortSignal,
): Promise<string> {
    let data: unknown;
    try {
        data = await api.post<unknown>(WORKFLOW_DRAFT_INSTRUCTIONS_PATH, {
            workflow_scope: 'personal',
            name: workflow.name,
            description: workflow.description,
            brief: taskName,
        }, signal);
    } catch (problem) {
        if (signal.aborted) throw problem;
        const message = problem instanceof ApiError && problem.message ? clipped(problem.message, SERVER_TEXT_LIMIT) : '';
        throw new Error(message || "Couldn't draft instructions. Try again.");
    }
    const instructions = isRecord(data) && typeof data.instructions === 'string' ? data.instructions.trim() : '';
    if (!instructions) throw new Error("The assistant didn't return instructions. Try again.");
    if (instructions.length > WORKFLOW_TASK_INSTRUCTIONS_LIMIT) {
        throw new Error(`The drafted instructions are longer than ${WORKFLOW_TASK_INSTRUCTIONS_LIMIT.toLocaleString()} characters, so they weren't added. Try again, or write them yourself.`);
    }
    return instructions;
}
