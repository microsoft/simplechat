// conversationReferences.ts

import { api } from './apiClient';
import { chatHrefForConversation, readConversationParam } from './conversationUrl';
import { insertContextToken, removeContextToken, sanitizeContextLabel } from './chatContextTokens';

export interface ConversationReference {
    kind: 'conversation';
    id: string;
    message_ids?: string[];
}

export interface ConversationSource extends ConversationReference {
    title: string;
    revision?: string;
    last_updated?: string;
}

export interface DraftConversationReference extends ConversationSource {
    token: string;
    attachment: 'mention' | 'selection' | 'both';
}

export interface ConversationReferenceResolution {
    references: ConversationSource[];
    excerpts: Array<{ conversation_id: string; message_id: string; role: string; content: string; timestamp?: string }>;
    partial: boolean;
    revision: string;
    prompt: string;
    destination_config?: ConversationHandoffDestinationConfig;
}

export type ConversationHandoffStatus =
    | 'queued'
    | 'starting'
    | 'running'
    | 'completed'
    | 'failed'
    | 'needs_attention'
    | 'cancelled';

export interface ConversationHandoffDestinationConfig {
    conversation_id?: string;
    model_name?: string;
    model_deployment?: string;
    model_id?: string;
    model_endpoint_id?: string;
    model_provider?: string;
    reasoning_effort?: string;
    revision?: string;
}

export interface ConversationHandoff {
    id: string;
    kind?: 'handoff';
    request_id?: string;
    source_conversation_id: string;
    source_conversation_title?: string;
    destination_conversation_id: string;
    destination_conversation_title?: string;
    instruction: string;
    conversation_references?: ConversationReference[];
    status: ConversationHandoffStatus;
    error?: string;
    cancel_requested?: boolean;
    created_at?: number | string;
    updated_at?: number | string;
    destination_config?: ConversationHandoffDestinationConfig;
    destination_user_message_id?: string;
    destination_message_id?: string;
}

export const HANDOFF_STATUS_LABELS: Readonly<Record<ConversationHandoffStatus, string>> = {
    queued: 'Queued',
    starting: 'Starting',
    running: 'Running',
    completed: 'Completed',
    failed: 'Failed',
    needs_attention: 'Needs attention',
    cancelled: 'Cancelled',
};

export function isPrivateConversation(
    conversation: Record<string, unknown> | null | undefined,
    userId?: string | null,
): boolean {
    if (!conversation) return false;
    if (userId && conversation.user_id && String(conversation.user_id) !== userId) return false;
    if (conversation.conversation_kind === 'collaborative' || conversation.conversation_kind === 'collaboration_source') {
        return false;
    }
    const chatType = String(conversation.chat_type ?? '').trim();
    if (chatType === 'personal_multi_user' || chatType.startsWith('group') || chatType.startsWith('public')) {
        return false;
    }
    if (conversation.collaboration_conversation_id || conversation.is_shared || conversation.group_id
        || conversation.public_workspace_id || conversation.is_deleted || conversation.deleted || conversation.deleted_at) {
        return false;
    }
    if (Array.isArray(conversation.shared_with) && conversation.shared_with.length > 0) return false;
    if (Array.isArray(conversation.participants) && conversation.participants.length > 0) return false;
    const scope = conversation.scope;
    if (scope && typeof scope === 'object' && 'type' in scope
        && !['personal', 'user'].includes(String((scope as { type?: unknown }).type ?? 'personal'))) {
        return false;
    }
    if (conversation.scope_type && !['personal', 'user'].includes(String(conversation.scope_type))) {
        return false;
    }
    if (Array.isArray(conversation.context) && conversation.context.some((entry) =>
        Boolean(entry && typeof entry === 'object'
            && (entry as { type?: unknown }).type === 'primary'
            && ((entry as { scope?: unknown }).scope === 'group' || (entry as { scope?: unknown }).scope === 'public')))) {
        return false;
    }
    return true;
}

export const CONVERSATION_REFERENCE_LIMIT = 5;
export const CONVERSATION_REFERENCE_MIME = 'application/x-simplechat-conversation-reference+json';
const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/;

export function conversationReferenceRequests(references: readonly ConversationReference[] = []): ConversationReference[] {
    const seen = new Set<string>();
    return references.filter((reference) => reference.kind === 'conversation' && ID.test(reference.id)
        && !seen.has(reference.id) && Boolean(seen.add(reference.id))).map((reference) => ({
        kind: 'conversation', id: reference.id,
        ...(reference.message_ids?.length ? { message_ids: [...reference.message_ids] } : {}),
    }));
}

export function storedConversationReferences(value: unknown): ConversationSource[] {
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is ConversationSource => Boolean(item && item.kind === 'conversation'
        && typeof item.id === 'string' && ID.test(item.id))).map((item) => ({
        ...item, title: typeof item.title === 'string' ? item.title : 'Conversation source',
    }));
}

function outsideCode(text: string, index: number): boolean {
    let fence = '';
    let inline = 0;
    const prefix = text.slice(0, index);
    for (const line of prefix.split('\n')) {
        const marker = /^\s{0,3}(`{3,}|~{3,})/.exec(line);
        if (marker) {
            if (!fence) fence = marker[1][0];
            else if (fence === marker[1][0]) fence = '';
            continue;
        }
        if (fence) continue;
        for (const match of line.matchAll(/(?<!\\)`+/g)) {
            const size = match[0].length;
            if (!inline) inline = size;
            else if (inline === size) inline = 0;
        }
    }
    return !fence && !inline;
}

export function readConversationQuery(text: string, caret: number): { query: string; start: number; end: number } | null {
    const end = Math.max(0, Math.min(caret, text.length));
    const start = text.lastIndexOf('~', end - 1);
    if (start < 0 || (start > 0 && !/\s/.test(text[start - 1])) || !outsideCode(text, start)) return null;
    const query = text.slice(start + 1, end);
    if (/^[\s~/\\[]/.test(query) || /[\n\r[\]~`]/.test(query) || query.length > 60
        || /[~[/\\]/.test(text[start + 1] ?? '')) return null;
    return { query, start, end };
}

export function parseConversationTokens(text: string) {
    return [...text.matchAll(/~\[([^\[\]\n]+)\]/g)].filter((match) => {
        const index = match.index ?? 0;
        return (!index || /\s/.test(text[index - 1])) && outsideCode(text, index);
    }).map((match) => ({ token: match[0], start: match.index!, end: match.index! + match[0].length }));
}

export function reconcileConversationReferences(text: string, references: readonly DraftConversationReference[] = []): DraftConversationReference[] {
    const present = new Set(parseConversationTokens(text).map((item) => item.token));
    return references.flatMap((reference) => reference.attachment === 'selection' || present.has(reference.token)
        ? [reference] : reference.attachment === 'both' ? [{ ...reference, attachment: 'selection' as const }] : []);
}

export function addConversationReference(references: readonly DraftConversationReference[], source: ConversationSource,
    attachment: DraftConversationReference['attachment'] = 'selection'): DraftConversationReference[] {
    const previous = references.find((reference) => reference.id === source.id);
    if (previous) return references.map((reference) => reference.id === source.id ? {
        ...reference, ...source, token: reference.token,
        attachment: reference.attachment === attachment ? attachment : 'both',
    } : reference);
    if (references.length >= CONVERSATION_REFERENCE_LIMIT) throw new Error('Use at most five conversation sources. Remove one first.');
    const base = sanitizeContextLabel(source.title) || 'Untitled conversation';
    const taken = new Set(references.map((reference) => reference.token));
    let label = base;
    let suffix = 2;
    while (taken.has(`~[${label}]`)) label = `${base.slice(0, 65)} (${suffix++})`;
    return [...references, { ...source, token: `~[${label}]`, attachment }];
}

export { insertContextToken as insertConversationToken, removeContextToken as removeConversationToken };

export function searchConversationReferences(query: string, excludeId?: string | null, offset = 0, searchContent = false) {
    const params = new URLSearchParams({ query, offset: String(offset), limit: '10', search_content: String(searchContent) });
    if (excludeId) params.set('exclude_conversation_id', excludeId);
    return api.get<{ conversations: ConversationSource[]; has_more: boolean; next_offset: number; partial: boolean }>(`/api/conversation-references?${params}`);
}

export function resolveConversationReferences(references: readonly ConversationReference[], destinationId?: string | null, query?: string) {
    return api.post<ConversationReferenceResolution>('/api/conversation-references/resolve', {
        conversation_references: conversationReferenceRequests(references),
        ...(destinationId ? { destination_conversation_id: destinationId } : {}),
        ...(query ? { query } : {}),
    });
}

/** Plain text is versioned and retains ID and origin, even outside rich clipboard clients. */
export function portableConversationReference(source: ConversationReference, origin: string): string {
    return `simplechat-conversation:v1:${new URL(`/v2${chatHrefForConversation(source.id)}`, origin).href}`;
}

export function readPortableConversationReference(text: string, origin: string): ConversationReference | null {
    if (!text.startsWith('simplechat-conversation:v1:')) return null;
    try {
        const url = new URL(text.slice('simplechat-conversation:v1:'.length).trim());
        const id = readConversationParam(url.searchParams);
        if (url.origin !== origin || url.pathname !== '/v2/chat' || !id || !ID.test(id)) return null;
        return { kind: 'conversation', id };
    } catch { return null; }
}

export function readClipboardConversationReference(
    clipboardData: Pick<DataTransfer, 'getData'> | null | undefined,
    origin: string,
): ConversationReference | null {
    if (!clipboardData) return null;
    const plain = clipboardData.getData('text/plain')?.trim() ?? '';
    const fromPlain = plain ? readPortableConversationReference(plain, origin) : null;
    if (fromPlain) return fromPlain;
    const rawMime = clipboardData.getData(CONVERSATION_REFERENCE_MIME)?.trim() ?? '';
    if (!rawMime) return null;
    const fromPortableMime = readPortableConversationReference(rawMime, origin);
    if (fromPortableMime) return fromPortableMime;
    try {
        const parsed = JSON.parse(rawMime) as { kind?: unknown; id?: unknown; origin?: unknown };
        if (parsed && typeof parsed === 'object' && (!parsed.origin || parsed.origin === origin)
            && parsed.kind === 'conversation' && typeof parsed.id === 'string' && ID.test(parsed.id)) {
            return { kind: 'conversation', id: parsed.id };
        }
    } catch { /* Ignore invalid clipboard payloads. */ }
    return null;
}

export async function listConversationHandoffs(conversationId: string, destinationPreviewId?: string | null) {
    const params = new URLSearchParams({ conversation_id: conversationId });
    if (destinationPreviewId) params.set('destination_preview_id', destinationPreviewId);
    const response = await api.get<{ handoffs?: ConversationHandoff[]; destination_config?: ConversationHandoffDestinationConfig } | ConversationHandoff[]>(
        `/api/conversation-handoffs?${params}`,
    );
    if (Array.isArray(response)) {
        return { handoffs: response, destination_config: undefined };
    }
    return {
        handoffs: Array.isArray(response?.handoffs) ? response.handoffs : [],
        destination_config: response?.destination_config,
    };
}

export async function previewConversationHandoffDestination(destinationId: string) {
    const response = await api.get<{ destination_config?: ConversationHandoffDestinationConfig }>(
        `/api/conversation-handoffs/destination/${encodeURIComponent(destinationId)}`,
    );
    return response?.destination_config;
}

export async function createConversationHandoff(request: {
    source_conversation_id: string;
    destination_conversation_id: string;
    instruction: string;
    conversation_references?: readonly ConversationReference[];
    request_id?: string;
    destination_config_revision?: string;
}): Promise<ConversationHandoff> {
    const response = await api.post<{ handoff?: ConversationHandoff } | ConversationHandoff>('/api/conversation-handoffs', {
        source_conversation_id: request.source_conversation_id,
        destination_conversation_id: request.destination_conversation_id,
        instruction: request.instruction.trim(),
        conversation_references: conversationReferenceRequests(
            request.conversation_references ?? [{ kind: 'conversation', id: request.source_conversation_id }],
        ),
        ...(request.request_id ? { request_id: request.request_id } : {}),
        ...(request.destination_config_revision ? { destination_config_revision: request.destination_config_revision } : {}),
    });
    return (response && typeof response === 'object' && 'handoff' in response && response.handoff)
        ? response.handoff
        : response as ConversationHandoff;
}

export async function cancelConversationHandoff(handoffId: string, destinationConversationId: string): Promise<ConversationHandoff> {
    const response = await api.post<{ handoff?: ConversationHandoff } | ConversationHandoff>(
        `/api/conversation-handoffs/${encodeURIComponent(handoffId)}/cancel`,
        { destination_conversation_id: destinationConversationId },
    );
    return (response && typeof response === 'object' && 'handoff' in response && response.handoff)
        ? response.handoff
        : response as ConversationHandoff;
}
