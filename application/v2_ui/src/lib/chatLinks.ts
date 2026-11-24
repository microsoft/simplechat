// chatLinks.ts
// Typed client contract for stored workspace chat launch links.

import { api, API_BASE } from './apiClient';
import type { DocumentSourceSelection } from './documentSourceSelection';

export const CHAT_LINK_LIFETIMES = [
    { value: 7, label: '7 days' },
    { value: 30, label: '30 days' },
    { value: 90, label: '90 days' },
    { value: 365, label: '1 year' },
    { value: null, label: 'Never expires' },
] as const;

export interface ChatLinkRouting {
    kind: 'agent' | 'model';
    selection_key: string;
    display_name?: string;
    scope_type?: string;
    scope_id?: string | null;
}

export interface ChatLinkWorkspace {
    kind: 'personal' | 'group' | 'public';
    id?: string;
    display_name?: string;
}

export interface ChatLinkCreatePayload {
    routing: Pick<ChatLinkRouting, 'kind' | 'selection_key'>;
    workspace: ChatLinkWorkspace;
    document_source_selection: DocumentSourceSelection;
    reasoning_effort: string | null;
    lifetime_days: number | null;
}

export interface ChatLinkSummary {
    reference: string;
    path: string;
    created_at: string;
    expires_at: string | null;
    lifetime_days: number | null;
    routing: ChatLinkRouting;
    workspace: ChatLinkWorkspace;
    document_count: number | null;
    all_documents: boolean;
    reasoning_effort: string | null;
    reasoning_effort_bound?: boolean;
    created_by_user_id?: string;
}

export interface ResolvedChatLink extends ChatLinkSummary {
    document_source_selection: DocumentSourceSelection;
}

export interface ChatLinkList {
    links: ChatLinkSummary[];
    continuation_token: string | null;
    has_more: boolean;
}

export function safeChatLinkUrl(path: string): string {
    if (!/^\/l\/[A-Za-z0-9_-]{22}$/.test(path)) {
        return '';
    }
    const base = API_BASE && /^https?:\/\//i.test(API_BASE)
        ? API_BASE
        : typeof window !== 'undefined' ? window.location.origin : '';
    return base ? new URL(path, `${base.replace(/\/$/, '')}/`).toString() : path;
}

export function createChatLink(payload: ChatLinkCreatePayload) {
    return api.post<ResolvedChatLink>('/api/chat-links', {
        routing: {
            kind: payload.routing.kind,
            selection_key: payload.routing.selection_key,
        },
        workspace: payload.workspace.kind === 'personal'
            ? { kind: 'personal' }
            : { kind: payload.workspace.kind, id: payload.workspace.id },
        document_source_selection: payload.document_source_selection,
        reasoning_effort: payload.reasoning_effort,
        lifetime_days: payload.lifetime_days,
    });
}

export function resolveChatLink(reference: string) {
    return api.get<ResolvedChatLink>(`/api/chat-links/${encodeURIComponent(reference)}`);
}

export function listChatLinks(continuationToken?: string | null) {
    const params = new URLSearchParams({ page_size: '25' });
    if (continuationToken) params.set('continuation_token', continuationToken);
    return api.get<ChatLinkList>(`/api/chat-links?${params.toString()}`);
}

export function revokeChatLink(reference: string) {
    return api.delete<void>(`/api/chat-links/${encodeURIComponent(reference)}`);
}

export function listControlCenterChatLinks(continuationToken?: string | null) {
    const params = new URLSearchParams({ page_size: '25' });
    if (continuationToken) params.set('continuation_token', continuationToken);
    return api.get<ChatLinkList>(`/api/v2/control-center/chat-links?${params.toString()}`);
}

export function revokeControlCenterChatLink(reference: string) {
    return api.delete<void>(
        `/api/v2/control-center/chat-links/${encodeURIComponent(reference)}`,
    );
}

export function chatLinkLifetimeLabel(days: number | null): string {
    if (days === null) return 'Never expires';
    return days === 365 ? '1 year' : `${days} days`;
}

export function chatLinkExpiryLabel(value: string | null): string {
    if (!value) return 'Never';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Unknown';
    return date.toLocaleString();
}

export function chatLinkDocumentLabel(link: Pick<ChatLinkSummary, 'all_documents' | 'document_count'>): string {
    if (link.all_documents) return 'All documents';
    const count = link.document_count ?? 0;
    return `${count} ${count === 1 ? 'document' : 'documents'}`;
}

export function chatLinkReasoningLabel(
    routing: Pick<ChatLinkRouting, 'kind'>,
    reasoningEffort: string | null,
): string {
    if (routing.kind === 'agent') return 'Agent setting';
    if (!reasoningEffort) return 'Model default';
    return reasoningEffort.charAt(0).toUpperCase() + reasoningEffort.slice(1);
}
