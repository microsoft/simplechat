// promptKnowledge.ts

import { api } from './apiClient';
import type { ContextItem } from './chatContext';
import type { Json } from './types';

export interface PromptKnowledgeSource {
    document_id: string;
    chunk_id: string;
    title: string;
    page_number?: string | number;
    excerpt: string;
    group_id?: string;
    public_workspace_id?: string;
}

export interface PromptKnowledgeValue {
    value: string;
    sources: PromptKnowledgeSource[];
}

export interface PromptKnowledgeUnresolved {
    key: string;
    reason: string;
    alternatives?: PromptKnowledgeValue[];
}

export interface PromptKnowledgeRequest {
    prompt_content: string;
    composer_text: string;
    conversation_id?: string;
    conversation_kind: 'personal' | 'collaborative';
    selected_document_ids: string[];
    tags: string[];
    doc_scope: string;
    active_group_ids: string[];
    active_public_workspace_ids: string[];
    document_filter_mode: 'union' | 'intersection';
    search_all: boolean;
    scope_selected: boolean;
    context_items: {
        kind: ContextItem['kind'];
        id: string;
        scope: Pick<ContextItem['scope'], 'kind' | 'id'>;
    }[];
    agent_info?: Json;
    known_values?: Record<string, string>;
}

export interface PromptKnowledgeResponse {
    values: (PromptKnowledgeValue & { key: string })[];
    unresolved: PromptKnowledgeUnresolved[];
}

export function fillPromptFromKnowledge(
    request: PromptKnowledgeRequest,
    variables: { key: string; name: string }[],
    signal: AbortSignal,
): Promise<PromptKnowledgeResponse> {
    return api.post('/api/v2/prompts/fill-variables', { ...request, variables }, signal);
}
