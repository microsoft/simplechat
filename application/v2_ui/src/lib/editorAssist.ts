// editorAssist.ts
// The agent and action editors' side of POST /api/agents/assist and /api/actions/assist: the view
// of the draft a request sends, the answer it accepts, and what a failure means for the reader.
//
// The editor describes its draft as a flat list of fields, each with a JSON-pointer-like path, and
// the server answers with a candidate value for each path. Everything the server sends back is
// untrusted: the answer is checked field by field, the change list is recomputed here from the
// values, and every string is plain text for the UI to render as a text node.

import { apiUrl, CREDENTIALS_MODE } from './apiClient';
import { codePointLength, codePointPrefix } from './codePoints';
import { isRecord } from './workspaceAuthoring';

export type EditorAssistKind = 'agent' | 'action';

export const EDITOR_ASSIST_PATHS: Readonly<Record<EditorAssistKind, string>> = {
    agent: '/api/agents/assist',
    action: '/api/actions/assist',
};

/** The server counts the instruction in code points (EDITOR_ASSIST_INSTRUCTION_MAX_LENGTH). */
export const EDITOR_ASSIST_INSTRUCTION_LIMIT = 2000;
export const EDITOR_ASSIST_TURN_TEXT_LIMIT = 4000;
/** Conversation items: ten whole exchanges, so a replay never starts with an orphan reply. */
export const EDITOR_ASSIST_MAX_TURNS = 20;
export const EDITOR_ASSIST_REPLY_LIMIT = 2000;
export const EDITOR_ASSIST_MAX_NOTES = 10;
export const EDITOR_ASSIST_NOTE_LIMIT = 300;
/** The server stops at about 150 seconds; the browser waits a little longer for its answer. */
export const EDITOR_ASSIST_DEADLINE_MS = 170_000;
/** The prefix of a choice value that names an item the assistant drafted in this turn. */
export const EDITOR_ASSIST_NEW_ITEM_PREFIX = 'new:';

const SERVER_TEXT_LIMIT = 1000;
const LABEL_LIMIT = 200;
const MAX_CHANGES = 300;
const MAX_WARNINGS = 20;
const MAX_NEW_ITEMS = 5;
const MAX_RETRY_AFTER_SECONDS = 3600;
const REPLAY_LABELS = 12;
const REPLAY_LABEL_LIMIT = 120;
const PATH_PATTERN = /^\/[A-Za-z0-9_/]{1,200}$/;
const SECTION_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;
const HANDLE_PATTERN = /^new:[A-Za-z0-9_-]{1,32}$/;

// The characters the server refuses in text. Tab, LF and CR are allowed.
const CONTROL_CHARACTERS = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g;
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g;

export const EDITOR_ASSIST_UNREADABLE_MESSAGE = "The assistant's answer couldn't be read. Nothing was changed.";
export const EDITOR_ASSIST_STALE_MESSAGE = 'Nothing was applied because the draft changed while Ask AI was working. Send it again to use the current draft.';

export type EditorAssistFieldKind =
    | 'text' | 'textarea' | 'number' | 'boolean' | 'select' | 'choices' | 'lines' | 'web_sources';

export interface EditorAssistOption {
    readonly value: string;
    readonly label?: string;
    readonly description?: string;
}

/** One field the assistant may read and set. Secrets are never described. */
export interface EditorAssistField {
    readonly path: string;
    readonly label: string;
    readonly section?: string;
    readonly kind: EditorAssistFieldKind;
    readonly help?: string;
    readonly required?: boolean;
    readonly min?: number;
    readonly max?: number;
    readonly integer?: boolean;
    readonly max_length?: number;
    readonly max_items?: number;
    readonly options?: readonly EditorAssistOption[];
    readonly read_only?: boolean;
}

export interface EditorAssistSection {
    readonly id: string;
    readonly label: string;
}

/** A select whose value picks an extra set of fields, such as an action's type. */
export interface EditorAssistVariant {
    readonly path: string;
    readonly fields: Readonly<Record<string, readonly EditorAssistField[]>>;
}

/** New items the agent assistant may draft and assign, such as actions. */
export interface EditorAssistNewItemsSpec {
    readonly target: string;
    readonly noun: string;
    readonly max: number;
    readonly types: readonly EditorAssistOption[];
    readonly common: readonly EditorAssistField[];
    readonly variants?: Readonly<Record<string, readonly EditorAssistField[]>>;
}

export type EditorAssistValues = Readonly<Record<string, unknown>>;

/** The draft as the assistant sees it. */
export interface EditorAssistView {
    readonly sections: readonly EditorAssistSection[];
    readonly fields: readonly EditorAssistField[];
    readonly values: EditorAssistValues;
    readonly variant?: EditorAssistVariant;
    readonly newItems?: EditorAssistNewItemsSpec;
    readonly notes?: readonly string[];
}

export interface EditorAssistScope {
    readonly kind: 'personal' | 'group' | 'global';
    readonly id?: string;
}

export interface EditorAssistConversationItem {
    readonly role: 'user' | 'assistant';
    readonly text: string;
}

export interface EditorAssistRequest {
    readonly scope: EditorAssistScope['kind'];
    readonly group_id?: string;
    readonly submission_id: string;
    readonly instruction: string;
    readonly conversation: readonly EditorAssistConversationItem[];
    readonly focus?: string;
    readonly sections: readonly EditorAssistSection[];
    readonly fields: readonly EditorAssistField[];
    readonly values: EditorAssistValues;
    readonly variant?: EditorAssistVariant;
    readonly new_items?: EditorAssistNewItemsSpec;
    readonly notes?: readonly string[];
}

export interface EditorAssistNewItem {
    readonly handle: string;
    readonly type: string;
    readonly values: EditorAssistValues;
}

export interface EditorAssistChange {
    readonly path: string;
    readonly label: string;
    readonly section: string | null;
}

export interface EditorAssistWarning {
    readonly code: string;
    readonly message: string;
    readonly paths: readonly string[];
}

export interface EditorAssistResponse {
    readonly submissionId: string;
    readonly outcome: 'changed' | 'explained';
    readonly reply: string;
    readonly candidate: { readonly values: EditorAssistValues; readonly newItems: readonly EditorAssistNewItem[] } | null;
    readonly changes: readonly EditorAssistChange[];
    readonly warnings: readonly EditorAssistWarning[];
}

export interface EditorAssistFailure {
    readonly status: number;
    readonly code: string;
    readonly message: string;
    /** Wait this long before sending again: a 429, or a throttled 503. */
    readonly retryAfterSeconds: number | null;
}

export type EditorAssistPostResult =
    | { readonly ok: true; readonly response: EditorAssistResponse }
    | { readonly ok: false; readonly aborted: true }
    | { readonly ok: false; readonly aborted?: false; readonly failure: EditorAssistFailure };

// ---------------------------------------------------------------------------------------------
// Values
// ---------------------------------------------------------------------------------------------

/** Text the server accepts: no control characters except tab, LF and CR, and no lone surrogate. */
export function editorAssistText(value: string): string {
    return value.replace(CONTROL_CHARACTERS, '').replace(LONE_SURROGATE, '\ufffd');
}

function stable(value: unknown, depth = 0): unknown {
    if (depth > 40) return null;
    if (Array.isArray(value)) return value.map((item) => stable(item, depth + 1));
    if (isRecord(value)) {
        const result: Record<string, unknown> = {};
        for (const key of Object.keys(value).sort()) {
            if (value[key] !== undefined) result[key] = stable(value[key], depth + 1);
        }
        return result;
    }
    if (typeof value === 'number' && !Number.isFinite(value)) return null;
    return value === undefined ? null : value;
}

/** A value's JSON with sorted keys, so two equal values always compare equal. */
export function editorAssistKey(value: unknown): string {
    return JSON.stringify(stable(value)) ?? 'null';
}

export function sameEditorAssistValue(left: unknown, right: unknown): boolean {
    return editorAssistKey(left) === editorAssistKey(right);
}

/** Whether a value counts as empty, as the server's `_is_blank` does. */
export function editorAssistBlank(value: unknown): boolean {
    if (value === null || value === undefined) return true;
    if (typeof value === 'string') return !value.trim();
    if (Array.isArray(value)) return value.length === 0;
    return false;
}

/** Every field of the view, including each variant's and new-item fields, by path. */
export function editorAssistFieldIndex(view: EditorAssistView): Map<string, EditorAssistField> {
    const index = new Map<string, EditorAssistField>();
    for (const field of view.fields) index.set(field.path, field);
    for (const fields of Object.values(view.variant?.fields ?? {})) {
        for (const field of fields) if (!index.has(field.path)) index.set(field.path, field);
    }
    return index;
}

/** The fields active for `values`: the common ones and the selected variant's. */
export function editorAssistActiveFields(view: EditorAssistView, values: EditorAssistValues): EditorAssistField[] {
    const active = [...view.fields];
    if (view.variant) {
        const selected = values[view.variant.path];
        if (typeof selected === 'string') active.push(...(view.variant.fields[selected] ?? []));
    }
    return active;
}

// ---------------------------------------------------------------------------------------------
// Request
// ---------------------------------------------------------------------------------------------

export class EditorAssistRequestError extends Error {}

export interface EditorAssistRequestInput {
    readonly scope: EditorAssistScope;
    readonly submissionId: string;
    readonly instruction: string;
    readonly view: EditorAssistView;
    readonly conversation: readonly EditorAssistConversationItem[];
    readonly focus?: string | null;
}

function cappedNote(note: string): string {
    const text = editorAssistText(note).replace(/\s+/g, ' ').trim();
    return codePointPrefix(text, EDITOR_ASSIST_NOTE_LIMIT);
}

export function buildEditorAssistRequest(input: EditorAssistRequestInput): EditorAssistRequest {
    const instruction = editorAssistText(input.instruction).trim();
    if (!instruction) throw new EditorAssistRequestError('Type what you want Ask AI to do.');
    if (codePointLength(instruction) > EDITOR_ASSIST_INSTRUCTION_LIMIT) {
        throw new EditorAssistRequestError(`Keep the request to ${EDITOR_ASSIST_INSTRUCTION_LIMIT} characters or fewer.`);
    }
    const { view, scope } = input;
    if (scope.kind === 'group' && !scope.id) throw new EditorAssistRequestError("Ask AI couldn't tell which group this is.");
    const sectionIds = new Set(view.sections.map((section) => section.id));
    const values: Record<string, unknown> = {};
    for (const field of editorAssistActiveFields(view, view.values)) {
        if (Object.hasOwn(view.values, field.path)) values[field.path] = view.values[field.path];
    }
    const notes = (view.notes ?? []).map(cappedNote).filter(Boolean).slice(0, EDITOR_ASSIST_MAX_NOTES);
    const focus = input.focus && sectionIds.has(input.focus) ? input.focus : undefined;
    return {
        scope: scope.kind,
        ...(scope.kind === 'group' && scope.id ? { group_id: scope.id } : {}),
        submission_id: input.submissionId,
        instruction,
        conversation: input.conversation.slice(-EDITOR_ASSIST_MAX_TURNS),
        ...(focus ? { focus } : {}),
        sections: view.sections,
        fields: view.fields,
        values,
        ...(view.variant ? { variant: view.variant } : {}),
        ...(view.newItems ? { new_items: view.newItems } : {}),
        ...(notes.length ? { notes } : {}),
    };
}

// ---------------------------------------------------------------------------------------------
// Conversation replay
// ---------------------------------------------------------------------------------------------

export type EditorAssistTurnState = 'none' | 'applied' | 'partly_undone' | 'undone';

export interface EditorAssistReplayTurn {
    readonly instruction: string;
    readonly reply: string;
    readonly state: EditorAssistTurnState;
    readonly changes: readonly string[];
}

function clipped(value: string, limit: number): string {
    const text = value.replace(/\s+/g, ' ').trim();
    return codePointLength(text) > limit ? `${codePointPrefix(text, limit - 1).trimEnd()}…` : text;
}

function replaySuffix(turn: EditorAssistReplayTurn): string {
    const labels = turn.changes.map((label) => clipped(editorAssistText(label), REPLAY_LABEL_LIMIT)).filter(Boolean);
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
        default:
            return '';
    }
}

function replayItem(role: 'user' | 'assistant', text: string, suffix = ''): EditorAssistConversationItem | null {
    const body = editorAssistText(text).trim();
    const combined = suffix ? (body ? `${body}\n\n${suffix}` : suffix) : body;
    const capped = codePointPrefix(combined, EDITOR_ASSIST_TURN_TEXT_LIMIT);
    return capped.trim() ? { role, text: capped } : null;
}

/** The last ten completed exchanges, oldest first; each reply says what became of its changes. */
export function editorAssistConversation(turns: readonly EditorAssistReplayTurn[]): EditorAssistConversationItem[] {
    const items: EditorAssistConversationItem[] = [];
    for (const turn of turns.slice(-(EDITOR_ASSIST_MAX_TURNS / 2))) {
        const user = replayItem('user', turn.instruction);
        const assistant = replayItem('assistant', turn.reply, replaySuffix(turn));
        if (user) items.push(user);
        if (assistant) items.push(assistant);
    }
    return items.slice(-EDITOR_ASSIST_MAX_TURNS);
}

// ---------------------------------------------------------------------------------------------
// Response
// ---------------------------------------------------------------------------------------------

function serverText(value: unknown, limit: number): string | null {
    if (typeof value !== 'string') return null;
    const text = editorAssistText(value).trim();
    return text ? codePointPrefix(text, limit) : null;
}

function validPath(value: unknown): value is string {
    return typeof value === 'string' && PATH_PATTERN.test(value);
}

function parseValues(value: unknown): Record<string, unknown> | null {
    if (!isRecord(value)) return null;
    const result: Record<string, unknown> = {};
    for (const [path, item] of Object.entries(value)) {
        if (!validPath(path)) return null;
        result[path] = item;
    }
    return result;
}

function parseNewItem(value: unknown): EditorAssistNewItem | null {
    if (!isRecord(value)) return null;
    const { handle, type } = value;
    if (typeof handle !== 'string' || !HANDLE_PATTERN.test(handle)) return null;
    if (typeof type !== 'string' || !type || type.length > 128) return null;
    const values = parseValues(value.values);
    return values ? { handle, type, values } : null;
}

function parseChange(value: unknown): EditorAssistChange | null {
    if (!isRecord(value) || !validPath(value.path)) return null;
    const label = serverText(value.label, LABEL_LIMIT) ?? value.path;
    const section = typeof value.section === 'string' && SECTION_PATTERN.test(value.section) ? value.section : null;
    return { path: value.path, label, section };
}

function parseWarning(value: unknown): EditorAssistWarning | null {
    if (!isRecord(value)) return null;
    const code = typeof value.code === 'string' && /^[a-z0-9_]{1,64}$/.test(value.code) ? value.code : null;
    const message = serverText(value.message, SERVER_TEXT_LIMIT);
    if (!code || !message) return null;
    const paths = Array.isArray(value.paths) ? value.paths.filter(validPath).slice(0, 50) : [];
    return { code, message, paths };
}

/** The answer, checked field by field, or null when it can't be used. */
export function parseEditorAssistResponse(value: unknown, submissionId: string): EditorAssistResponse | null {
    if (!isRecord(value) || value.submission_id !== submissionId) return null;
    const outcome = value.outcome;
    if (outcome !== 'changed' && outcome !== 'explained') return null;
    const reply = serverText(value.reply, EDITOR_ASSIST_REPLY_LIMIT);
    if (!reply) return null;
    let candidate: EditorAssistResponse['candidate'] = null;
    if (outcome === 'changed') {
        if (!isRecord(value.candidate)) return null;
        const values = parseValues(value.candidate.values);
        const rawItems = value.candidate.new_items ?? [];
        if (!values || !Array.isArray(rawItems) || rawItems.length > MAX_NEW_ITEMS) return null;
        const newItems: EditorAssistNewItem[] = [];
        for (const raw of rawItems) {
            const item = parseNewItem(raw);
            if (!item || newItems.some((existing) => existing.handle === item.handle)) return null;
            newItems.push(item);
        }
        candidate = { values, newItems };
    } else if (value.candidate !== null && value.candidate !== undefined) {
        return null;
    }
    const changes = Array.isArray(value.changes)
        ? value.changes.slice(0, MAX_CHANGES).map(parseChange).filter((item): item is EditorAssistChange => item !== null)
        : [];
    const warnings = Array.isArray(value.warnings)
        ? value.warnings.slice(0, MAX_WARNINGS).map(parseWarning).filter((item): item is EditorAssistWarning => item !== null)
        : [];
    return { submissionId, outcome, reply, candidate, changes, warnings };
}

const STATUS_FALLBACKS: Readonly<Record<number, string>> = {
    400: "The assistant couldn't use this request. Nothing was changed.",
    401: 'Your session expired. Sign in again to use Ask AI.',
    403: "Ask AI isn't available to you right now.",
    404: "This workspace couldn't be found.",
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
export function editorAssistRetryAfter(header: string | null, body: unknown, now = Date.now()): number | null {
    const text = (header ?? '').trim();
    if (/^\d{1,10}$/.test(text)) return clampRetryAfter(Number(text));
    if (text) {
        const date = Date.parse(text);
        if (!Number.isNaN(date)) return clampRetryAfter((date - now) / 1000);
    }
    const seconds = isRecord(body) ? body.retry_after_seconds : undefined;
    return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0 ? clampRetryAfter(seconds) : null;
}

const ONE_WORD_ERROR = /^[A-Za-z][A-Za-z0-9_]*$/;

/** What a failed request means for the reader. The server's text is shown as plain text. */
export function describeEditorAssistError(status: number, body: unknown, retryAfterHeader: string | null = null): EditorAssistFailure {
    const code = isRecord(body) && typeof body.code === 'string' && /^[a-z0-9_]{1,64}$/.test(body.code) ? body.code : '';
    const fallback = STATUS_FALLBACKS[status] ?? `The assistant request failed (status ${status}). Nothing was changed.`;
    const error = isRecord(body) ? serverText(body.error, SERVER_TEXT_LIMIT) : null;
    const sentence = isRecord(body) ? serverText(body.message, SERVER_TEXT_LIMIT) : null;
    const message = (error && ONE_WORD_ERROR.test(error) && sentence ? sentence : error) || fallback;
    const retryAfterSeconds = status === 429 || status === 503 ? editorAssistRetryAfter(retryAfterHeader, body) : null;
    return {
        status,
        code,
        message,
        retryAfterSeconds: status === 429 && retryAfterSeconds === null ? 1 : retryAfterSeconds,
    };
}

/**
 * POST one turn. A cancel through `signal` is `aborted`; the browser deadline and a lost
 * connection are failures the reader can retry.
 */
export async function postEditorAssist(
    kind: EditorAssistKind,
    body: EditorAssistRequest,
    signal: AbortSignal,
    deadlineMs = EDITOR_ASSIST_DEADLINE_MS,
): Promise<EditorAssistPostResult> {
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
        // A raw fetch rather than apiClient: ApiError drops the headers, and a throttled 429 carries
        // its wait in Retry-After.
        const response = await fetch(apiUrl(EDITOR_ASSIST_PATHS[kind]), {
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
            return { ok: false, failure: describeEditorAssistError(response.status, payload, response.headers.get('Retry-After')) };
        }
        const parsed = parseEditorAssistResponse(payload, body.submission_id);
        return parsed ? { ok: true, response: parsed } : {
            ok: false,
            failure: { status: response.status, code: 'unreadable', message: EDITOR_ASSIST_UNREADABLE_MESSAGE, retryAfterSeconds: null },
        };
    } catch {
        if (signal.aborted) return { ok: false, aborted: true };
        return {
            ok: false,
            failure: timedOut ? {
                status: 0, code: 'browser_timeout', retryAfterSeconds: null,
                message: 'The assistant took too long to answer. Nothing was changed. Try again, or ask for a smaller change.',
            } : {
                status: 0, code: 'network_error', retryAfterSeconds: null,
                message: "Couldn't reach the assistant. Nothing was changed. Check your connection and try again.",
            },
        };
    } finally {
        clearTimeout(timer);
        signal.removeEventListener('abort', stop);
    }
}

// ---------------------------------------------------------------------------------------------
// Applying and undoing
// ---------------------------------------------------------------------------------------------

/** One path a turn changed: its value before the turn and the value the turn left. */
export interface EditorAssistEntry {
    readonly path: string;
    readonly before: unknown;
    readonly after: unknown;
}

export interface EditorAssistTurnChange {
    readonly path: string;
    readonly label: string;
    readonly section: string | null;
}

/**
 * The patch a candidate makes to the live values: every path whose value differs. A changed
 * variant comes first, because it decides which other fields exist.
 */
export function editorAssistPatch(
    view: EditorAssistView,
    live: EditorAssistValues,
    candidate: EditorAssistValues,
): Record<string, unknown> {
    const active = new Set([
        ...editorAssistActiveFields(view, live).map((field) => field.path),
        ...editorAssistActiveFields(view, candidate).map((field) => field.path),
    ]);
    const index = editorAssistFieldIndex(view);
    const patch: Record<string, unknown> = {};
    const variantPath = view.variant?.path;
    if (variantPath && Object.hasOwn(candidate, variantPath) && !sameEditorAssistValue(live[variantPath], candidate[variantPath])) {
        patch[variantPath] = candidate[variantPath];
    }
    for (const [path, value] of Object.entries(candidate)) {
        if (path === variantPath || !active.has(path)) continue;
        if (index.get(path)?.read_only) continue;
        if (sameEditorAssistValue(live[path], value)) continue;
        if (editorAssistBlank(live[path]) && editorAssistBlank(value)) continue;
        patch[path] = value;
    }
    return patch;
}

/**
 * The changes a turn made, labelled from the view. A field that went away with the old type is
 * left out: the type change itself says so.
 */
export function editorAssistTurnChanges(view: EditorAssistView, entries: readonly EditorAssistEntry[]): EditorAssistTurnChange[] {
    const index = editorAssistFieldIndex(view);
    return entries
        .filter((entry) => entry.after !== undefined && !sameEditorAssistValue(entry.before, entry.after))
        .map((entry) => {
            const field = index.get(entry.path);
            return { path: entry.path, label: field?.label ?? entry.path, section: field?.section ?? null };
        });
}

export interface EditorAssistUndoPlan {
    readonly patch: Record<string, unknown>;
    readonly reverted: readonly string[];
    readonly skipped: readonly string[];
}

/**
 * What undoing a turn does now: each path still holding the turn's value goes back; a path
 * changed again since is skipped. When the turn changed the variant and that goes back, the old
 * variant's fields go back too.
 */
export function editorAssistUndoPlan(
    entries: readonly EditorAssistEntry[],
    before: EditorAssistValues,
    live: EditorAssistValues,
    variantPath?: string,
): EditorAssistUndoPlan {
    const patch: Record<string, unknown> = {};
    const reverted: string[] = [];
    const skipped: string[] = [];
    for (const entry of entries) {
        if (sameEditorAssistValue(live[entry.path], entry.before)) continue;
        if (!sameEditorAssistValue(live[entry.path], entry.after)) {
            skipped.push(entry.path);
            continue;
        }
        patch[entry.path] = entry.before;
        reverted.push(entry.path);
    }
    if (variantPath && Object.hasOwn(patch, variantPath)) {
        const ordered: Record<string, unknown> = { [variantPath]: patch[variantPath] };
        for (const [path, value] of Object.entries(before)) {
            if (path !== variantPath && !Object.hasOwn(patch, path) && !entries.some((entry) => entry.path === path)) ordered[path] = value;
        }
        for (const [path, value] of Object.entries(patch)) if (path !== variantPath) ordered[path] = value;
        return { patch: ordered, reverted, skipped };
    }
    return { patch, reverted, skipped };
}

/** A short label for the turn, used in its Undo button. */
export function editorAssistShortLabel(text: string, limit = 60): string {
    return clipped(text, limit);
}
