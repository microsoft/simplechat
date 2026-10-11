// pendingActionReview.ts

import { isPendingAction, m365Request, type PendingAction } from './approvalsApi';
import {
    editorAssistPatch, editorAssistTurnChanges, sameEditorAssistValue,
    type EditorAssistField, type EditorAssistValues, type EditorAssistView,
} from './editorAssist';

export interface PendingReviewDraft {
    subject: string;
    body: string;
    content_type: string;
    to_recipients?: string[];
    cc_recipients?: string[];
    bcc_recipients?: string[];
    attendee_recipients?: string[];
    start_datetime?: string;
    end_datetime?: string;
    timezone?: string;
    location?: string;
    teams_meeting_requested?: boolean;
}

export interface PendingReviewHistory {
    id: string;
    kind: string;
    submission_id?: string;
    instruction?: string;
    reply?: string;
    attribution?: string;
    created_at?: string;
    saved?: boolean;
    before?: PendingReviewDraft;
    after?: PendingReviewDraft;
    applied?: boolean;
    warnings?: readonly { code: string; message: string; paths: readonly string[] }[];
}

export interface PendingReviewWireResponse {
    pending_action: PendingAction;
    fields?: PendingReviewDraft;
    expected_version: string;
    assist_enabled?: boolean;
    timezone_aliases?: Readonly<Record<string, string>>;
    assist_turn_id?: string;
    history?: {
        items: Array<{
            id: string; kind: string; submission_id?: string; instruction?: string; reply?: string;
            origin?: string; created_at?: string; saved?: boolean; applied?: boolean;
            from_fields?: PendingReviewDraft; fields?: PendingReviewDraft; candidate_fields?: PendingReviewDraft;
            warnings?: PendingReviewHistory['warnings'];
        }>;
        next_cursor?: string;
    };
}

export interface PendingReviewResponse {
    pending_action: PendingAction;
    draft: PendingReviewDraft;
    version: string;
    assist_enabled: boolean;
    timezone_aliases?: Readonly<Record<string, string>>;
    history?: PendingReviewHistory[];
    continuation_token?: string;
}

export function pendingReviewPath(id: string, suffix = ''): string {
    return `/api/msgraph/pending-actions/${encodeURIComponent(id)}/review${suffix}`;
}

/** The server still authorizes every read/write; shared and timed actions get no editor. */
export function canEditPendingAction(action: PendingAction): boolean {
    return action.can_edit === true && action.viewer_is_owner !== false
        && action.action_mode === 'manual'
        && !['sending', 'sent', 'cancelled', 'canceled', 'failed', 'recovery_required'].includes(action.status);
}

export function pendingActionLinkLabel(action: PendingAction): string {
    if (action.graph_resource_type === 'calendar') return 'Open calendar event in Outlook';
    if (action.web_link_kind === 'sent') return 'Open sent message in Outlook';
    if (action.web_link_kind === 'retained_draft') return 'Open retained draft in Outlook';
    return 'Open draft in Outlook';
}

/** Never relabel a pre-send URL as the sent item. Legacy retained drafts stay explicit. */
export function pendingActionCanLink(action: PendingAction): boolean {
    if (action.link_pending === true || action.link_status === 'pending' || action.link_status === 'unavailable') return false;
    if (action.status === 'sent' && action.graph_resource_type !== 'calendar') {
        return action.web_link_kind === 'sent' || action.web_link_kind === 'retained_draft';
    }
    return true;
}

export function pendingReviewHasDateTimeOffset(value: string): boolean {
    return /T.*(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(value);
}

/** Format explicit instants in the selected zone; untouched draft strings keep their precision/offset. */
export function pendingReviewDateTimeInput(value: string, timezone?: string, aliases: Readonly<Record<string, string>> = {}): string {
    if (!pendingReviewHasDateTimeOffset(value)) return value.replace(/(\.\d{3})\d+$/, '$1');
    if (!timezone) return value;
    try {
        const normalized = value.replace(/(\.\d{3})\d+(?=Z|[+-]\d{2}(?::?\d{2})?$)/i, '$1')
            .replace(/([+-]\d{2})(\d{2})$/, '$1:$2').replace(/([+-]\d{2})$/, '$1:00');
        const instant = new Date(normalized);
        if (!Number.isFinite(instant.getTime())) return value;
        const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
            timeZone: aliases[timezone] ?? timezone, calendar: 'gregory', numberingSystem: 'latn', hourCycle: 'h23',
            year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
        }).formatToParts(instant).map((part) => [part.type, part.value]));
        const fraction = /\.\d+/.test(value) ? `.${String(instant.getUTCMilliseconds()).padStart(3, '0')}` : '';
        return `${parts.year.padStart(4, '0')}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}${fraction}`;
    } catch {
        return value;
    }
}

const field = (name: string, label: string, kind: EditorAssistField['kind'] = 'text'): EditorAssistField => ({
    path: `/${name}`, label, section: name === 'body' ? 'body' : 'details', kind,
    max_length: name === 'body' ? 50000 : 500,
    ...(kind === 'lines' ? { max_items: 100 } : {}),
});

export function pendingReviewView(draft: PendingReviewDraft, calendar: boolean): EditorAssistView {
    const fields = calendar ? [
        field('subject', 'Title'), field('attendee_recipients', 'Attendees', 'lines'),
        field('start_datetime', 'Start'), field('end_datetime', 'End'), field('timezone', 'Time zone'),
        field('location', 'Location'), field('teams_meeting_requested', 'Teams meeting', 'boolean'),
    ] : [
        field('subject', 'Subject'), field('to_recipients', 'To', 'lines'),
        field('cc_recipients', 'Cc', 'lines'), field('bcc_recipients', 'Bcc', 'lines'),
    ];
    fields.push(field('body', 'Body', 'textarea'));
    fields.push({
        path: '/content_type', label: 'Body format', section: 'body', kind: 'select',
        options: [{ value: 'Text', label: 'Plain text' }, { value: 'HTML', label: 'HTML' }],
    });
    return {
        sections: [{ id: 'details', label: 'Details' }, { id: 'body', label: 'Body' }],
        fields,
        values: Object.fromEntries(fields.map(({ path }) => [path, draft[path.slice(1) as keyof PendingReviewDraft] ?? ''])),
    };
}

/** Shared proposal validation restricts AI to the editor's typed allowlist. */
export function applyPendingReviewValues(
    draft: PendingReviewDraft, values: EditorAssistValues, calendar: boolean,
): PendingReviewDraft {
    const view = pendingReviewView(draft, calendar);
    const patch = editorAssistPatch(view, view.values, values);
    const next = { ...draft };
    for (const [path, value] of Object.entries(patch)) {
        const spec = view.fields.find((item) => item.path === path);
        if (!spec) continue;
        if (spec.kind === 'boolean' && typeof value !== 'boolean') continue;
        if (spec.kind === 'select' && !spec.options?.some((option) => option.value === value)) continue;
        if (spec.kind === 'lines' && (!Array.isArray(value) || value.length > 100
            || value.some((item) => typeof item !== 'string' || item.length > 320))) continue;
        if (spec.kind !== 'boolean' && spec.kind !== 'lines'
            && (typeof value !== 'string' || value.length > (spec.max_length ?? 1000))) continue;
        Object.assign(next, { [path.slice(1)]: value });
    }

    return next;
}

export function pendingReviewChanges(before: PendingReviewDraft, after: PendingReviewDraft, calendar: boolean) {
    const view = pendingReviewView(after, calendar);
    const beforeValues = pendingReviewView(before, calendar).values;
    const entries = Object.entries(view.values).map(([path, value]) => ({ path, before: beforeValues[path], after: value }))
        .filter((entry) => !sameEditorAssistValue(entry.before, entry.after));
    return editorAssistTurnChanges(view, entries);
}

/** Apply a persisted proposal only where its original working value still matches. */
export function pendingReviewApplySuggestion(
    before: PendingReviewDraft, after: PendingReviewDraft, draft: PendingReviewDraft, calendar: boolean,
) {
    const candidate = applyPendingReviewValues(before,
        Object.fromEntries(Object.entries(after).map(([name, value]) => [`/${name}`, value])), calendar);
    const original = pendingReviewView(before, calendar).values;
    const proposed = pendingReviewView(candidate, calendar).values;
    const live = pendingReviewView(draft, calendar).values;
    const patch: Record<string, unknown> = {};
    const applied: string[] = [];
    const skipped: string[] = [];
    for (const [path, value] of Object.entries(proposed)) {
        if (sameEditorAssistValue(original[path], value)) continue;
        if (sameEditorAssistValue(live[path], original[path])) {
            patch[path] = value;
            applied.push(path);
        } else if (!sameEditorAssistValue(live[path], value)) {
            skipped.push(path);
        }
    }
    return { draft: applyPendingReviewValues(draft, patch, calendar), applied, skipped };
}

export function fetchPendingReview(id: string, signal?: AbortSignal) {
    return m365Request<PendingReviewWireResponse>(pendingReviewPath(id), { signal })
        .then((response) => checkedReview(id, pendingReviewFromWire(response)));
}

export function savePendingReview(id: string, version: string, draft: PendingReviewDraft, attribution: string, assistTurnId?: string, signal?: AbortSignal) {
    return m365Request<PendingReviewWireResponse>(pendingReviewPath(id), {
        method: 'PATCH', body: { expected_version: version, fields: draft, origin: attribution, ...(assistTurnId ? { assist_turn_id: assistTurnId } : {}) }, signal,
    }).then((response) => checkedReview(id, pendingReviewFromWire(response)));
}

export function pendingReviewHistoryFromWire(response: PendingReviewWireResponse) {
    return {
        history: (response.history?.items ?? []).map((record): PendingReviewHistory => ({
            id: record.id, kind: record.kind, submission_id: record.submission_id, instruction: record.instruction,
            reply: record.reply, attribution: record.origin, created_at: record.created_at,
            saved: record.saved, applied: record.applied, before: record.from_fields,
            after: record.fields ?? record.candidate_fields, warnings: record.warnings,
        })).reverse(),
        continuation_token: response.history?.next_cursor ?? '',
    };
}

export function pendingReviewFromWire(response: PendingReviewWireResponse): PendingReviewResponse {
    return {
        pending_action: response.pending_action, draft: response.fields as PendingReviewDraft,
        version: response.expected_version, assist_enabled: response.assist_enabled !== false,
        timezone_aliases: response.timezone_aliases && typeof response.timezone_aliases === 'object' && !Array.isArray(response.timezone_aliases)
            ? Object.fromEntries(Object.entries(response.timezone_aliases).slice(0, 256)
                .filter(([name, zone]) => name.length <= 100 && typeof zone === 'string' && zone.length <= 100)) : {},
        ...pendingReviewHistoryFromWire(response),
    };
}

function checkedReview(id: string, response: PendingReviewResponse): PendingReviewResponse {
    if (!response || !isPendingAction(response.pending_action) || response.pending_action.id !== id
        || !canEditPendingAction(response.pending_action)
        || typeof response.version !== 'string' || !response.version
        || response.version !== response.pending_action.version
        || !response.draft || typeof response.draft.subject !== 'string' || typeof response.draft.body !== 'string') {
        throw new Error('The saved owner draft could not be verified. Refresh its status before continuing.');
    }
    return response;
}

export function fetchPendingReviewHistory(id: string, token: string, signal?: AbortSignal) {
    const query = new URLSearchParams({ cursor: token, limit: '20' });
    return m365Request<PendingReviewWireResponse>(
        `/api/msgraph/pending-actions/${encodeURIComponent(id)}/history?${query.toString()}`, { signal },
    ).then((response) => checkedReview(id, pendingReviewFromWire(response)));
}
